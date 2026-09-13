import time
from selenium.webdriver.common.by import By
from betscraper.driver import build_driver
from betscraper.consent import dismiss_overlays
from betscraper import selectors as sel
from betscraper.match_standings import extract_team_id, open_over_under_tab, wait_for_line_table, parse_team_row_from_table

url = "https://www.betexplorer.com/football/usa/mls/fc-dallas-portland-timbers/xG4QJkVA/"
home_team = "FC Dallas"
away_team = "Portland Timbers"

driver = build_driver(headless=True)
try:
    t0 = time.time()
    driver.get(url)
    dismiss_overlays(driver)
    print(f"[{time.time()-t0:.1f}s] Page loaded, overlays dismissed")

    home_id = extract_team_id(driver, home_team)
    away_id = extract_team_id(driver, away_team)
    print(f"[{time.time()-t0:.1f}s] home_id={home_id} away_id={away_id}")

    tabs_before = driver.find_elements(By.XPATH, sel.STANDINGS_OU_TAB_XPATH)
    print(f"[{time.time()-t0:.1f}s] O/U tab elements found immediately: {len(tabs_before)}")

    opened = open_over_under_tab(driver, wait_seconds=20.0)
    print(f"[{time.time()-t0:.1f}s] open_over_under_tab returned: {opened}")

    if opened:
        table = wait_for_line_table(driver, 2.5, wait_seconds=15.0)
        print(f"[{time.time()-t0:.1f}s] table found: {table is not None}")
        if table and home_id:
            row = parse_team_row_from_table(table, home_id)
            print(f"[{time.time()-t0:.1f}s] home row for 2.5: {row}")
finally:
    driver.quit()
