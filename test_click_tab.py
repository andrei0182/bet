import time
import re
from selenium.webdriver.common.by import By
from betscraper.driver import build_driver
from betscraper.consent import dismiss_overlays

url = "https://www.betexplorer.com/football/usa/mls/fc-dallas-portland-timbers/xG4QJkVA/"
_TS_PATTERN = re.compile(r"[?&]ts=([A-Za-z0-9]+)")

driver = build_driver(headless=True)
try:
    t0 = time.time()
    driver.get(url)
    dismiss_overlays(driver)

    tabs = driver.find_elements(By.CSS_SELECTOR, "[data-tab='ou']")
    print(f"Found {len(tabs)} elements with data-tab='ou' at {time.time()-t0:.1f}s")
    if tabs:
        driver.execute_script("arguments[0].click();", tabs[0])
        print(f"Clicked O/U tab at {time.time()-t0:.1f}s")

    found = False
    for i in range(30):
        if _TS_PATTERN.search(driver.page_source):
            print(f"ts= found after {time.time()-t0:.1f}s (poll #{i})")
            found = True
            break
        time.sleep(1)
    if not found:
        print(f"ts= still NOT found after {time.time()-t0:.1f}s")
finally:
    driver.quit()
