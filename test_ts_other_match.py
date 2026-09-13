import time
import re
from betscraper.driver import build_driver
from betscraper.consent import dismiss_overlays
import pandas as pd

_TS_PATTERN = re.compile(r"[?&]ts=([A-Za-z0-9]+)")

df = pd.read_excel('output/matches.xlsx')
row = df[df['league'].str.contains('SPAIN', na=False)].iloc[0]
url = row['match_url']
print("Testing:", row['home_team'], "vs", row['away_team'], url)

driver = build_driver(headless=True)
try:
    t0 = time.time()
    driver.get(url)
    dismiss_overlays(driver)
    found = False
    for i in range(45):
        if _TS_PATTERN.search(driver.page_source):
            print(f"ts= found after {time.time()-t0:.1f}s")
            found = True
            break
        time.sleep(1)
    if not found:
        print(f"ts= NOT found after {time.time()-t0:.1f}s")
finally:
    driver.quit()
