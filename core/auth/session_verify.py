import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

INDIAMART_URL = "https://seller.indiamart.com/"

def verify_session(slot_id: str):
    base_dir = Path(__file__).resolve().parents[2]
    profile_dir = base_dir / "browser_profiles" / slot_id

    if not profile_dir.exists():
        print("❌ No browser profile found. Login required.")
        return

    print(f"\n🔁 SESSION VERIFY — {slot_id}")
    print(f"📂 Using profile: {profile_dir}")
    print(f"🌐 Opening: {INDIAMART_URL}")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False
        )
        page = context.new_page()
        page.goto(INDIAMART_URL, wait_until="load", timeout=60000)

        print("\n🟢 CHECK THIS:")
        print("• If seller dashboard loads → SESSION VALID")
        print("• If login page appears → SESSION EXPIRED\n")

        input("👉 Press ENTER to close browser...")
        context.close()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python session_verify.py <slot_id>")
        sys.exit(1)

    verify_session(sys.argv[1])