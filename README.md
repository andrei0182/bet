# BetExplorer scraper

Selenium-based scraper for betexplorer.com: match list + 1X2 odds, Over/Under
2.5 odds, live/completed/scheduled state, and per-match Over/Under
1.5/2.5/3.5 team stats (when a standings table exists for that competition).

## ⚠️ Selectors are unverified — read this before running

This project was built in a sandboxed environment whose network policy
blocks outbound access to betexplorer.com, so **none of the CSS selectors in
`betscraper/selectors.py` could be tested against the live site.** They are
reasonable best-effort defaults for BetExplorer's general layout, not
confirmed values.

Before trusting any output:

1. Install deps: `pip install -r requirements.txt`
2. Run the selector-discovery helper against a real page (this automates the
   manual DevTools inspection from the task's Step 2):
   ```
   python tools/inspect_page.py "https://www.betexplorer.com/football/" --keep-open
   ```
   Run it once each for a completed match, a live match, a scheduled match,
   and a cup/Champions-League-style match page. It prints every table,
   tab/dropdown, and "standings"-like element with a ready-to-use selector.
3. Update the values in `betscraper/selectors.py` to match — it's the single
   file every other module reads from, nothing else hard-codes a selector.
4. Also confirm the date-navigation URL pattern in DevTools → Network while
   clicking the site's calendar (Step 3), and adjust `DATE_URL_TEMPLATE` in
   the same file if it differs.

## Usage

```bash
pip install -r requirements.txt

# Odds only, for today:
python main.py --output output/today.xlsx

# A specific date, plus per-match Over/Under stats (slower — one page load per match):
python main.py --date 2026-09-15 --with-stats --output output/2026-09-15.xlsx

# Cap how many matches get per-match stats while you're still verifying selectors:
python main.py --with-stats --max-matches 5 --no-headless --verbose
```

## Project layout

- `betscraper/selectors.py` — every CSS selector, in one place (edit this first)
- `betscraper/driver.py` — headless Chrome via `webdriver-manager`
- `betscraper/models.py` — `Match`, `Odds1X2`, `OddsOverUnder`, `TeamOverUnderStats`
- `betscraper/match_list.py` — Steps 3–6: date navigation, 1X2 extraction, O/U view switch + merge, status classification
- `betscraper/match_state.py` — live/completed/scheduled classification
- `betscraper/match_stats.py` — Steps 7–8: standings-table eligibility check, O/U 1.5/2.5/3.5 per-team stats
- `betscraper/export.py` — flatten to a `pandas.DataFrame` and write `.xlsx`
- `main.py` — CLI entrypoint
- `tools/inspect_page.py` — selector-discovery helper (Step 2, automated)

## Design notes

- All waits use `WebDriverWait` + `expected_conditions` (or a value-changed
  predicate for the O/U sub-tab clicks), never a fixed `time.sleep` — per
  Steps 4 and 8.
- Stats eligibility is decided by checking for the standings table element in
  the DOM, not by matching competition names against "Cup" — per Step 7,
  since Champions League/Europa League have no standings table either.
- 1X2 and Over/Under rows are merged by `(home_team, away_team, time)` as a
  natural key, computed in `Match.match_key()`.
