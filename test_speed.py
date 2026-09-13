import time
import pandas as pd
from betscraper.match_stats import scrape_match_stats

df = pd.read_excel('output/matches.xlsx')
sample = df.sample(20, random_state=1)

t0 = time.time()
for _, row in sample.iterrows():
    eligible, home_stats, away_stats, odds_ou = scrape_match_stats(
        row['match_url'], row['home_team'], row['away_team']
    )
    print(f"{row['home_team']} vs {row['away_team']}: eligible={eligible}")
elapsed = time.time() - t0
print(f"\nTotal: {elapsed:.1f}s for 20 matches ({elapsed/20:.2f}s/match avg)")
