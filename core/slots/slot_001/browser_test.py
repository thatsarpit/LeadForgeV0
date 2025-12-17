from playwright.sync_api import sync_playwright
import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
PROFILE_DIR = os.path.join(BASE_DIR, "browser_profiles", "slot_001")

print("🧪 Launching browser for slot_001")
print("📂 Profile:", PROFILE_DIR)

with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        PROFILE_DIR,
        headless=False,
        viewport={"width": 1280, "height": 800}
    )
    page = browser.new_page()
    page.goto("https://www.google.com")
    input("👉 Browser open. Press ENTER to close...")
    browser.close()