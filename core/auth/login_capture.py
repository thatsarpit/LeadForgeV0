import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

INDIAMART_URL = "https://seller.indiamart.com/"

def capture_login(slot_id: str):
    base_dir = Path(__file__).resolve().parents[2]
    profile_dir = base_dir / "browser_profiles" / slot_id
    profile_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n🔐 LOGIN CAPTURE MODE — {slot_id}")
    print(f"📂 Profile dir: {profile_dir}")
    print(f"🌐 Opening: {INDIAMART_URL}")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False
        )
        page = context.new_page()
        page.goto(INDIAMART_URL, wait_until="load", timeout=60000)

        print("\n🟢 ACTION REQUIRED:")
        print("1. Login manually in the opened browser")
        print("2. Ensure seller dashboard/home loads")
        print("3. Then return here and press ENTER\n")

        input("👉 Press ENTER after login is COMPLETE: ")
        context.close()

    print("✅ Login session saved successfully.\n")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python login_capture.py <slot_id>")
        sys.exit(1)

    capture_login(sys.argv[1])