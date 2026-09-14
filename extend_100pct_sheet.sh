#!/bin/bash
# extend_100pct_sheet.sh — [betexplorer/bet repo] extends the "100% Over 2.5"
# sheet's columns to include the underlying hit-rate counts (home/away
# over/under 2.5) for both teams — needed for the daily recommendation
# email's case-study text ("Team X went Over 2.5 in N/N games...").
# Run from the BetExplorer repo root: bash extend_100pct_sheet.sh
set -e

python3 << 'PYEOF_ANDREI'
path = "betscraper/export.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = '''    cols = ["league", "time", "home_team", "away_team", "odds_over", "prob_over_2.5"]'''
new = '''    cols = [
        "league", "time", "home_team", "away_team", "odds_over", "prob_over_2.5",
        "home_over_2.5", "home_under_2.5", "away_over_2.5", "away_under_2.5",
        "match_url",
    ]'''
if old not in content:
    raise SystemExit("ERROR: expected cols line not found verbatim — aborting without changes.")
content = content.replace(old, new, 1)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Patched betscraper/export.py: '100% Over 2.5' sheet now includes hit-rate counts and match_url.")
PYEOF_ANDREI

echo "Verifying syntax..."
python -m py_compile betscraper/*.py main.py tools/*.py && echo "OK — syntax valid."
