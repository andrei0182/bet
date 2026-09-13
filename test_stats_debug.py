import pandas as pd
from betscraper.driver import build_driver
from betscraper.consent import dismiss_overlays
from betscraper.match_odds import extract_match_id, fetch_over_under_odds
from betscraper.match_standings import (
    discover_ts_token, extract_team_id, build_standings_url,
    fetch_standings_html, parse_team_over_under_row,
)

url = "https://www.betexplorer.com/football/usa/mls/fc-dallas-portland-timbers/xG4QJkVA/"
home_team = "FC Dallas"
away_team = "Portland Timbers"

driver = build_driver(headless=True)
try:
    driver.get(url)
    dismiss_overlays(driver)

    match_id = extract_match_id(url)
    print("match_id:", match_id)

    ts = discover_ts_token(driver)
    print("ts token:", ts)

    home_id = extract_team_id(driver, home_team)
    away_id = extract_team_id(driver, away_team)
    print("home_id:", home_id, "away_id:", away_id)

    if ts and match_id:
        standings_url = build_standings_url(url, ts, match_id)
        print("standings_url:", standings_url)
        html = fetch_standings_html(driver, standings_url)
        print("html length:", len(html) if html else None)
        if html and home_id:
            row = parse_team_over_under_row(html, home_id, 2.5)
            print("home row for 2.5:", row)
        if html and away_id:
            row = parse_team_over_under_row(html, away_id, 2.5)
            print("away row for 2.5:", row)
finally:
    driver.quit()
