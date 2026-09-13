import time
import re
from betscraper.driver import build_driver
from betscraper.consent import dismiss_overlays

url = "https://www.betexplorer.com/football/england/premier-league/"
_TS_PATTERN = re.compile(r"[?&]ts=([A-Za-z0-9]+)")

driver = build_driver(headless=True)
try:
    t0 = time.time()
    driver.get(url)
    dismiss_overlays(driver)
    print(f"[{time.time()-t0:.1f}s] Page loaded, title: {driver.title}")

    match = _TS_PATTERN.search(driver.page_source)
    print(f"[{time.time()-t0:.1f}s] ts token: {match.group(1) if match else None}")
finally:
    driver.quit()
