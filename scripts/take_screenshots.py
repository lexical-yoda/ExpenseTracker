"""
Automated screenshot generator for README.
Run from project root: python scripts/take_screenshots.py
Requires: geckodriver, selenium, Flask app running on localhost:5000

Usage:
    python scripts/take_screenshots.py                    # Use default credentials
    python scripts/take_screenshots.py -u admin -p pass   # Custom credentials
"""

import time
import os
import argparse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

BASE_URL = "http://localhost:5000"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENSHOT_DIR = os.path.join(PROJECT_ROOT, "screenshots")

DESKTOP = (1400, 900)
MOBILE = (390, 844)

PAGES = [
    ("login", "/login", False),
    ("dashboard", "/", True),
    ("analytics", "/analytics", True),
    ("manage", "/manage", True),
    ("accounts", "/accounts", True),
]

THEMES = ["github-dark", "github-light"]


def setup_driver(width, height):
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument(f"--width={width}")
    opts.add_argument(f"--height={height}")
    driver = webdriver.Firefox(options=opts)
    driver.set_window_size(width, height)
    return driver


def login(driver, username, password):
    driver.get(f"{BASE_URL}/login")
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.NAME, "username")))
    driver.find_element(By.NAME, "username").send_keys(username)
    driver.find_element(By.NAME, "password").send_keys(password)
    driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
    WebDriverWait(driver, 10).until(EC.url_changes(f"{BASE_URL}/login"))
    time.sleep(1)


def set_theme(driver, palette, mode):
    """Set theme and trigger chart re-renders."""
    driver.execute_script(f"""
        localStorage.setItem('theme-palette', '{palette}');
        localStorage.setItem('theme-mode', '{mode}');
        document.documentElement.setAttribute('data-theme', '{palette}-{mode}');

        // Re-render Plotly charts with correct theme colors
        var style = getComputedStyle(document.documentElement);
        var bg = style.getPropertyValue('--surface').trim();
        var text = style.getPropertyValue('--text').trim();
        var grid = style.getPropertyValue('--border').trim();

        var plots = document.querySelectorAll('.js-plotly-plot');
        plots.forEach(function(plot) {{
            if (plot.layout) {{
                Plotly.relayout(plot, {{
                    'paper_bgcolor': bg,
                    'plot_bgcolor': bg,
                    'font.color': text,
                    'xaxis.gridcolor': grid,
                    'yaxis.gridcolor': grid,
                    'xaxis.color': text,
                    'yaxis.color': text,
                }});
            }}
        }});
    """)
    time.sleep(1)


def take_screenshot(driver, name):
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    driver.save_screenshot(path)
    print(f"  Saved: {name}.png")


def capture_all(username, password):
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)

    # Login once to get session cookies
    print("Logging in...")
    tmp_driver = setup_driver(*DESKTOP)
    login(tmp_driver, username, password)
    cookies = tmp_driver.get_cookies()
    tmp_driver.quit()
    time.sleep(1)

    for theme in THEMES:
        palette, mode = theme.rsplit("-", 1)

        # Desktop
        print(f"\n=== Desktop {theme} ===")
        driver = setup_driver(*DESKTOP)
        try:
            driver.get(f"{BASE_URL}/login")
            for cookie in cookies:
                clean = {k: cookie[k] for k in ("name", "value", "path") if k in cookie}
                driver.add_cookie(clean)

            # Login page screenshot
            set_theme(driver, palette, mode)
            take_screenshot(driver, f"login-{theme}")

            for page_name, path, needs_auth in PAGES:
                if page_name == "login":
                    continue

                driver.get(f"{BASE_URL}{path}")
                time.sleep(2)
                set_theme(driver, palette, mode)

                # Extra wait for chart pages
                if page_name in ("dashboard", "analytics"):
                    time.sleep(2)

                take_screenshot(driver, f"{page_name}-desktop-{theme}")
        finally:
            driver.quit()

        # Mobile
        print(f"\n=== Mobile {theme} ===")
        driver = setup_driver(*MOBILE)
        try:
            driver.get(f"{BASE_URL}/login")
            for cookie in cookies:
                clean = {k: cookie[k] for k in ("name", "value", "path") if k in cookie}
                driver.add_cookie(clean)

            for page_name, path, needs_auth in PAGES:
                if page_name == "login":
                    continue

                driver.get(f"{BASE_URL}{path}")
                time.sleep(2)
                set_theme(driver, palette, mode)

                if page_name in ("dashboard", "analytics"):
                    time.sleep(2)

                take_screenshot(driver, f"{page_name}-mobile-{theme}")
        finally:
            driver.quit()

    print(f"\nDone! {len(THEMES) * (len(PAGES) * 2 - 1)} screenshots saved to screenshots/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate screenshots for README")
    parser.add_argument("-u", "--username", default="lexi", help="Login username")
    parser.add_argument("-p", "--password", default="newpassword", help="Login password")
    args = parser.parse_args()
    capture_all(args.username, args.password)
