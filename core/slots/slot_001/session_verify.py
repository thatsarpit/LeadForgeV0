from playwright.sync_api import sync_playwright
from pathlib import Path

SLOT_ID = "slot_001"
BASE_DIR = Path(__file__).resolve().parents[3]
PROFILE_DIR = BASE_DIR / "browser_profiles" / SLOT_ID
TARGET_URL = "https://seller.indiamart.com/"

def main():
    print(f"🔁 SESSION VERIFY — {SLOT_ID}")
    print(f"📂 Using profile: {PROFILE_DIR}")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            args=["--start-maximized"]
        )

        page = context.new_page()
        print(f"🌐 Opening: {TARGET_URL}")
        page.goto(TARGET_URL, timeout=60000)

        print("\n🟢 CHECK THIS:")
        print("• If seller dashboard loads → SESSION VALID")
        print("• If login page appears → SESSION EXPIRED")

        input("\n👉 Press ENTER to close browser...")
        context.close()

if __name__ == "__main__":
    main()