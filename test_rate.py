import time
import pandas as pd
from betscraper.driver import build_driver
from betscraper.match_stats import scrape_match_stats

df = pd.read_excel('output/matches.xlsx')
sample = df[df['league'].str.contains('GERMANY|ITALY|FRANCE|SPAIN|USA', na=False, regex=True)].sample(5, random_state=7)

driver = build_driver(headless=True)
try:
    for _, row in sample.iterrows():
        t0 = time.time()
        eligible, home_stats, away_stats, odds_ou = scrape_match_stats(
            driver, row['match_url'], row['home_team'], row['away_team']
        )
        elapsed = time.time() - t0
        print(f"{row['home_team']} vs {row['away_team']}: eligible={eligible} time={elapsed:.1f}s home={home_stats} away={away_stats}")
finally:
    driver.quit()
