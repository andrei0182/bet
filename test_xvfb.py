import time
from betscraper.driver import build_driver
from betscraper.consent import dismiss_overlays
from betscraper.match_standings import extract_team_id, open_over_under_tab, wait_for_line_table, parse_team_row_from_table

url = "https://www.betexplorer.com/football/italy/serie-c-group-a/lumezzane-renate/WOsMnh8C/"
home_team = "Lumezzane"
away_team = "Renate"

driver = build_driver(headless=False)  # non-headless, needs Xvfb
try:
    t0 = time.time()
    driver.get(url)
    dismiss_overlays(driver)
    print(f"[{time.time()-t0:.1f}s] Page loaded")

    home_id = extract_team_id(driver, home_team)
    away_id = extract_team_id(driver, away_team)
    print(f"[{time.time()-t0:.1f}s] home_id={home_id} away_id={away_id}")

    opened = open_over_under_tab(driver, wait_seconds=25.0)
    print(f"[{time.time()-t0:.1f}s] open_over_under_tab returned: {opened}")

    if opened:
        table = wait_for_line_table(driver, 2.5, wait_seconds=15.0)
        print(f"[{time.time()-t0:.1f}s] table found: {table is not None}")
        if table and home_id:
            row_data = parse_team_row_from_table(table, home_id)
            print(f"[{time.time()-t0:.1f}s] home row for 2.5: {row_data}")
finally:
    driver.quit()
