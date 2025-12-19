"""
Export decrypted cookies from a Playwright profile into slots/<id>/session.enc.
Use this after a successful manual login to avoid re-auth during scraping.
"""

import sys
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def export_cookies(slot_id: str):
    base_dir = Path(__file__).resolve().parents[2]
    profile_dir = base_dir / "browser_profiles" / slot_id
    slot_dir = base_dir / "slots" / slot_id
    session_file = slot_dir / "session.enc"

    if not profile_dir.exists():
        raise FileNotFoundError(f"Profile not found: {profile_dir}")
    if not slot_dir.exists():
        raise FileNotFoundError(f"Slot dir not found: {slot_dir}")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=True,
        )
        cookies = context.cookies()
        context.close()

    # Keep only IndiaMart-related cookies to limit exposure
    filtered = [
        c for c in cookies
        if "indiamart" in (c.get("domain") or "") or "indiamart" in (c.get("name") or "")
    ]

    session_file.write_text(json.dumps(filtered or cookies, indent=2))
    print(f"✅ Cookies exported to {session_file} ({len(filtered or cookies)} entries)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m core.auth.export_cookies <slot_id>")
        sys.exit(1)

    export_cookies(sys.argv[1])
