import pandas as pd
from betscraper.driver import build_driver
from betscraper.match_stats import scrape_match_stats

df = pd.read_excel('output/matches.xlsx')
row = df[df['league'] == 'USA: MLS'].iloc[0]
match_url = row['match_url']
home = row['home_team']
away = row['away_team']

print(f"Testing: {home} vs {away}")
print(f"URL: {match_url}")

driver = build_driver(headless=True)
try:
    eligible, home_stats, away_stats, odds_ou = scrape_match_stats(driver, match_url, home, away)
    print("stats_eligible:", eligible)
    print("home_stats:", home_stats)
    print("away_stats:", away_stats)
    print("odds_ou:", odds_ou)
finally:
    driver.quit()
