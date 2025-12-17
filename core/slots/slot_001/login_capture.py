from playwright.sync_api import sync_playwright
from pathlib import Path

SLOT_NAME = "slot_001"
BASE_DIR = Path(__file__).resolve().parents[3]
PROFILE_DIR = BASE_DIR / "browser_profiles" / SLOT_NAME
LOGIN_URL = "https://seller.indiamart.com/"

def main():
    print(f"🔐 LOGIN CAPTURE MODE — {SLOT_NAME}")
    print(f"📂 Profile dir: {PROFILE_DIR}")
    print(f"🌐 Opening: {LOGIN_URL}\n")

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            args=["--start-maximized"],
        )

        page = context.pages[0] if context.pages else context.new_page()
        page.goto(LOGIN_URL, wait_until="load")

        print("🟢 ACTION REQUIRED:")
        print("1. Login manually in the opened browser")
        print("2. Ensure seller dashboard/home loads")
        print("3. Then return here and press ENTER\n")

        input("👉 Press ENTER after login is COMPLETE: ")

        context.close()
        print("✅ Login session saved successfully.")

if __name__ == "__main__":
    main()