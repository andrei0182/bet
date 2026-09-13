import time
import re
from betscraper.driver import build_driver
from betscraper.consent import dismiss_overlays

url = "https://www.betexplorer.com/football/usa/mls/fc-dallas-portland-timbers/xG4QJkVA/"
_TS_PATTERN = re.compile(r"[?&]ts=([A-Za-z0-9]+)")

driver = build_driver(headless=True)
try:
    t0 = time.time()
    driver.get(url)
    dismiss_overlays(driver)
    print(f"After get+dismiss: {time.time()-t0:.1f}s")

    found = False
    for i in range(60):
        if _TS_PATTERN.search(driver.page_source):
            print(f"ts= found in page_source after {time.time()-t0:.1f}s (poll #{i})")
            found = True
            break
        time.sleep(1)
    if not found:
        print(f"ts= NOT found even after {time.time()-t0:.1f}s")
finally:
    driver.quit()
