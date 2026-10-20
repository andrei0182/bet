# BetExplorer scraper

Scrapes football match data from betexplorer.com for a given date: teams,
league, kick-off time, 1X2 odds, Over/Under 2.5 odds, and each team's
Over/Under 1.5/2.5/3.5 hit-rate stats for the season — exported to a
formatted, sortable Excel file plus a per-league summary sheet with
computed goal probabilities.

## Setup

```bash
pip install -r requirements.txt
```

## Running it — the command that creates the Excel file

Basic run for today, match list + 1X2 odds only:

```bash
python main.py
```

This creates `output/matches.xlsx` by default.

For a specific date, plus Over/Under odds and per-team hit-rate stats
(what most people want — this is the full report):

```bash
python main.py --date 2026-09-15 --with-stats
```

All options:

| Flag | Default | What it does |
|---|---|---|
| `--date YYYY-MM-DD` | today | Which day's matches to scrape. |
| `--output PATH` | `output/matches.xlsx` | Where to save the Excel file. |
| `--with-stats` | off | Also fetch Over/Under odds and per-team 1.5/2.5/3.5 hit-rate stats for every match (via plain HTTP requests — fast, no extra browser page load per match). Without this flag, only the match list and 1X2 odds are collected. |
| `--max-matches N` | none | Limit how many matches get `--with-stats` data — useful for a quick test run before doing a full day. |
| `--workers N` | 5 | Concurrent threads for the `--with-stats` requests. Higher is faster but risks `429 Too Many Requests` from the site under heavy load. |
| `--no-headless` | off | Show the Chrome window instead of running headless (for debugging the match-list step). |
| `--verbose` | off | Debug-level logging. |

Example — quick test on 20 matches before committing to a full day:

```bash
python main.py --date 2026-09-15 --with-stats --max-matches 20
```

Full day, once you're happy with a test run:

```bash
python main.py --date 2026-09-15 --with-stats --output output/2026-09-15.xlsx
```

## What's in the Excel file

Two sheets, both formatted as sortable/filterable Excel Tables with a
frozen header row:

- **Matches** — one row per match: league, kick-off time, status, teams,
  score, 1X2 odds, Over/Under 2.5 odds, each team's Over/Under 1.5/2.5/3.5
  hit-rate counts, and a computed `Probability Over {1.5,2.5,3.5}` column
  per line (the average of both teams' own season-long hit rate for that
  line — a transparent estimate you can sanity-check against the counts
  next to it, not a bookmaker/model-derived probability).
- **League Summary** — one row per league (plus an overall TOTAL row):
  match count, % of matches with stats available, average Over/Under
  odds, and average Over 2.5 probability.

Cup matches, single-leg knockout ties, and friendlies have no standings
table on betexplorer.com, so their stats/probability fields are left
blank (`Stats Available` = False) rather than causing an error — this is
expected, not a bug.

## Project layout

- `betscraper/selectors.py` — every CSS/XPath selector and AJAX endpoint
  URL, confirmed against the live site (see the `# Confirmed (date)`
  comments above each one for how/when).
- `betscraper/driver.py` — headless Chrome via `webdriver-manager`, used
  only for the initial daily match-list page.
- `betscraper/consent.py` — dismisses the cookie-consent banner.
- `betscraper/models.py` — `Match`, `Odds1X2`, `OddsOverUnder`,
  `TeamOverUnderStats` dataclasses.
- `betscraper/match_list.py` — loads the daily match-list page (with
  retry) and extracts teams/league/time/score/1X2 odds.
- `betscraper/match_state.py` — live/completed/scheduled classification.
- `betscraper/match_odds.py` — Over/Under odds via a plain HTTP request
  to a confirmed AJAX endpoint (no browser session needed).
- `betscraper/match_standings.py` — per-team Over/Under hit-rate stats,
  also via plain HTTP requests, fetched and cached once per league
  (not once per match) since the underlying data is a league-wide table.
- `betscraper/match_stats.py` — combines odds + hit-rate stats for one
  match into the `(stats_eligible, home_stats, away_stats, odds_ou)`
  tuple `main.py` uses.
- `betscraper/export.py` — builds the DataFrame, computes probability
  columns, and writes the formatted two-sheet `.xlsx`.
- `main.py` — CLI entrypoint.
- `tools/inspect_page.py` — selector-discovery helper, useful if
  betexplorer.com changes its markup in the future.

## Architecture note

Only the initial daily match-list page goes through Selenium/Chrome —
everything else (Over/Under odds, per-team hit-rate stats) is plain HTTP
requests (`requests`, with automatic retry on `429`/`5xx`), run
concurrently via a thread pool. This is what makes `--with-stats` fast
even for a day with 1000+ matches (minutes, not hours) — an earlier
version routed every per-match lookup through a real browser page load,
which was both far slower and, for the hit-rate stats specifically,
unreliably slow to render in a scripted Chrome session even though the
same data is available instantly via a direct HTTP request.

## Bot Telegram: gol în prima repriză

`fh_bot.py` (pachetul `fhgoals/`) publică pe canalul de Telegram:

- **dimineața** (`POST_MORNING`, implicit 08:00, ora României): meciurile zilei
  cu cea mai mare șansă de gol în prima repriză (cel mult `FH_MAX_PICKS`, implicit 10,
  doar peste `FH_MIN_PCT`, implicit 80%, și doar cele din oferta Superbet), cu
  procentul și cota Superbet „Prima repriză Peste 0.5”, plus rezultatele rămase de ieri;
- **live**: alertă dacă un meci ales e tot 0-0 în minutul `FH_MINUTE` (implicit 20)
  al primei reprize, cu cota live „Prima repriză Peste 0.5” și linkul spre meci;
- **după alertă**: meciul e urmărit până la pauză. La primul gol din prima repriză
  vine „⚽⚽⚽ GOOOOOOOL!” cu scorul și minutul, urmat de 🎉; dacă pauza vine la 0-0,
  „😞 Fără gol în prima repriză”, urmat de 😭. Un emoji trimis singur apare în Telegram
  mare și animat. Pentru un GIF anume, pune linkul lui în variabilele `FH_GIF_GOAL` /
  `FH_GIF_NO_GOAL` (GIF-ul vine atunci cu textul ca descriere);
- **seara** (`POST_EVENING`, implicit 23:30): rezultatul fiecărui pronostic (scorul la
  pauză), procentul zilei, alertele și procentul total.

### Cum se calculează procentul

Istoricul vine din paginile zilnice de rezultate BetExplorer (cu scorul la pauză),
ultimele 60 de zile, citite cu `requests` (fără Selenium). Pentru fiecare echipă se
iau ultimele `FH_LAST_N` (10) meciuri, fără amicale, și minimum `FH_MIN_MATCHES` (5):

- cât la sută din meciurile ei au avut gol în prima repriză;
- media golurilor marcate / primite în prima repriză (Poisson);
- rata de gol în prima repriză a ligii (ultimele 60 de meciuri din ligă).

Backtest pe 21 de zile (8213 meciuri, `python fh_bot.py --backtest 21`):

| Prag | Meciuri | Gol în R1 |
|---|---|---|
| media generală | 11413 | 73% |
| P >= 75% | 3661 | 78% |
| P >= 80% | 1872 | 80% |
| P >= 85% | 597 | 82% |
| P >= 90% | 66 | 85% |

Pronosticurile și rezultatele se păstrează în `data/fh_picks.csv` (comis de workflow).

### Configurare

1. Folosește botul și canalul din `andrei0182/live`: în acest repo, *Settings →
   Secrets and variables → Actions*, adaugă aceleași secrete `TELEGRAM_BOT_TOKEN`
   și `TELEGRAM_CHAT_ID`.
2. Opțional, variabile: `FH_MIN_PCT`, `FH_MAX_PICKS`, `FH_MINUTE`, `FH_LAST_N`,
   `FH_MIN_MATCHES`, `POST_MORNING`, `POST_EVENING`, `POSTS` (`off` oprește postările),
   `FH_GIF_GOAL`, `FH_GIF_NO_GOAL`.
3. *Actions → Gol în prima repriză (Telegram) → Run workflow* cu „Trimite doar un
   mesaj de test” bifat, apoi cu „Forțează o postare acum” = `dimineata`.

Workflow-ul (`.github/workflows/fh-telegram.yml`) pornește la fiecare 20 de minute
(minutele 2, 22, 42) și urmărește meciurile cel mult 18 minute, cu o verificare pe minut.
Prima rulare descarcă istoricul pe 60 de zile (câteva minute); apoi îl ține în cache.

Local:

```bash
pip install requests pytest
pytest tests/
TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python fh_bot.py --test-telegram
TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python fh_bot.py --morning --max-minutes 0
```
