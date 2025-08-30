"""
This script automates the generation and saving of a brand report from SmartScout.

After searching for a brand, it waits for the report analysis to complete and then
saves the entire report page as a local HTML file.

It is designed to be used with a browser that is already logged into SmartScout.
The script will connect to a persistent browser context, which means you need to
log in manually just once.

**Prerequisites:**
1. Python 3.7+ installed.
2. Playwright installed. To install, run the following commands in your terminal:
   pip install playwright
   playwright install

**How to run the script:**
1. **First-time setup (to log in):**
   - Run the script with the `--setup` argument: `python smartscout_downloader.py --setup`
   - This will open a browser window. Log into your SmartScout account as you normally would.
   - Once you are logged in, you can close the browser. The script will have saved your session.

2. **Running the automation:**
   - After the first-time setup, you can run the script to generate and save a report.
   - You will need to provide the name of the brand for the report.
   - The script will save the report as an HTML file in the same directory (e.g., 'example_brand_name_report.html').
   - Example: `python smartscout_downloader.py "Example Brand Name"`
"""
import os
import sys
import time
from playwright.sync_api import sync_playwright, expect

# --- Configuration ---
# The directory where your browser session data will be stored.
# This allows you to stay logged in between runs.
USER_DATA_DIR = "./playwright_user_data"
SMARTSCOUT_URL = "https://app.smartscout.com/app/tailored-report"

def run_automation(brand_name: str):
    """
    Main function to run the browser automation.
    """
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(USER_DATA_DIR, headless=False, slow_mo=500)
        page = context.new_page()

        print(f"Navigating to the Tailored Report page: {SMARTSCOUT_URL}")
        page.goto(SMARTSCOUT_URL)

        try:
            # 1. Use the search bar to find the brand.
            print(f"Searching for brand: '{brand_name}'")
            search_box_locator = page.get_by_placeholder("Enter Brand Name")
            expect(search_box_locator).to_be_visible(timeout=30000)
            search_box_locator.fill(brand_name)
            search_box_locator.press("Enter")

            # 2. Wait for the analysis prompt to appear.
            analysis_prompt_selector = "div.report-content-not-ready-prompt"
            print("Waiting for the 'Analyzing...' prompt to appear...")
            analysis_prompt = page.locator(analysis_prompt_selector)
            expect(analysis_prompt).to_be_visible(timeout=30000)
            print("'Analyzing...' prompt appeared.")

            # 3. Wait for the analysis prompt to disappear.
            print("Waiting for the analysis to complete...")
            # This can take a long time, so we use a generous timeout.
            expect(analysis_prompt).to_be_hidden(timeout=300000)  # 5 minute timeout
            print("Analysis complete.")

            # 4. Save the page content to an HTML file.
            html_content = page.content()
            file_name = f"{brand_name.replace(' ', '_').lower()}_report.html"
            with open(file_name, "w", encoding="utf-8") as f:
                f.write(html_content)

            print(f"\n✅ Success! Page saved to: {file_name}")

        except Exception as e:
            print(f"\n❌ An error occurred: {e}")
            print("Please ensure the brand name is correct and you are logged in.")
            print("You can try running the setup again with: python smartscout_downloader.py --setup")

        finally:
            print("Closing browser.")
            context.close()


def setup_session():
    """
    Opens a browser for the user to log in and save the session.
    """
    print("--- First-Time Setup ---")
    print(f"A browser window will now open. Please log into your SmartScout account.")
    print(f"The session will be saved in the '{USER_DATA_DIR}' directory.")
    print("You can close the browser once you are successfully logged in.")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(USER_DATA_DIR, headless=False)
        page = context.new_page()
        page.goto(SMARTSCOUT_URL)

        print("\nWaiting for you to log in and close the browser...")
        # The script will pause here, and the browser will remain open.
        # The user can perform the login and then close the browser manually.
        # The context manager will handle closing everything down when the user closes the browser.
        page.wait_for_event("close")

    print("\nSetup complete. Your session has been saved.")
    print("You can now run the script with a brand name to download reports.")


if __name__ == "__main__":
    if "--setup" in sys.argv:
        setup_session()
    elif len(sys.argv) > 1:
        brand_to_find = sys.argv[1]
        run_automation(brand_to_find)
    else:
        print("Usage:")
        print("  For first-time setup (to log in):")
        print("    python smartscout_downloader.py --setup")
        print("\n  To run the downloader:")
        print("    python smartscout_downloader.py \"Name of the Brand\"")
        sys.exit(1)
