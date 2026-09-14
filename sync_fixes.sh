#!/bin/bash
# sync_fixes.sh — MAJOR FIX: 1X2 odds have been unreliable via DOM scraping
# of the daily results page across an entire fresh run (0% coverage on all
# statuses, even after a wait-for-text fix) — the same pattern seen earlier
# today with the hit-rate stats widget: DOM-rendered async content is
# unreliable for scripted access, while the confirmed AJAX endpoint works
# instantly and reliably. CONFIRMED via curl (2026-09-14): a parallel AJAX
# endpoint exists for 1X2 (same URL shape as Over/Under, with "1x2" instead
# of "ou" in the path), needing no session/cookies, same as the O/U one.
# Adds fetch_1x2_odds() to match_odds.py and wires it into the --with-stats
# per-match pipeline (match_stats.py / main.py), overriding whatever the
# list-page DOM scrape did or didn't find. This means reliable 1X2 odds now
# require --with-stats (they're no longer guaranteed from the plain list
# scrape alone) — documented in README.
# Run from the repo root: bash sync_fixes.sh
set -e

python3 << 'PYEOF_ANDREI'
# ---- selectors.py: add the 1X2 AJAX endpoint template ----
path = "betscraper/selectors.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = 'OU_AJAX_URL_TEMPLATE = BASE_URL + "/match-odds/{match_id}/0/ou/bestOdds/?lang=en"'
new = (
    'OU_AJAX_URL_TEMPLATE = BASE_URL + "/match-odds/{match_id}/0/ou/bestOdds/?lang=en"\n'
    'X12_AJAX_URL_TEMPLATE = BASE_URL + "/match-odds/{match_id}/0/1x2/bestOdds/?lang=en"  '
    '# CONFIRMED 2026-09-14 via curl — same shape as OU_AJAX_URL_TEMPLATE, "1x2" market code instead of "ou"'
)
if old not in content:
    raise SystemExit("ERROR: OU_AJAX_URL_TEMPLATE line not found verbatim in selectors.py — aborting without changes.")
content = content.replace(old, new, 1)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Patched selectors.py: added X12_AJAX_URL_TEMPLATE.")
PYEOF_ANDREI

python3 << 'PYEOF_ANDREI'
# ---- match_odds.py: add fetch_1x2_odds() ----
path = "betscraper/match_odds.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old_import = "from .models import OddsOverUnder"
new_import = "from .models import Odds1X2, OddsOverUnder"
if old_import not in content:
    raise SystemExit("ERROR: models import line not found verbatim — aborting without changes.")
content = content.replace(old_import, new_import, 1)

old_pattern_block = '''_HANDICAP_BLOCK_TEMPLATE = r'data-all-handicap="{line}"[^>]*data-hp-1="([\\d.]*)"[^>]*data-hp-2="([\\d.]*)"\''''
new_pattern_block = old_pattern_block + '''

# CONFIRMED 2026-09-14 via curl: the 1X2 market's AJAX response has no
# handicap-style data-hp-1/data-hp-2 attributes (1X2 has no line/handicap
# concept) — instead the three aggregate odds sit in three consecutive
# elements inside the data-all-handicap="0" block, in 1/X/2 order:
#   <div class="oddsComparisonAll__odds_heads">
#     <div class="oddsComparisonAll__average_text" data-odd="1.75"></div>
#     <div class="oddsComparisonAll__average_text" data-odd="3.98"></div>
#     <div class="oddsComparisonAll__average_text" data-odd="3.89"></div>
_1X2_BLOCK_PATTERN = re.compile(
    r'data-all-handicap="0"[^>]*oddsComparisonAll__bestOdds.*?'
    r'oddsComparisonAll__odds_heads">\\s*'
    r'<div class="oddsComparisonAll__average_text" data-odd="([\\d.]*)"></div>'
    r'<div class="oddsComparisonAll__average_text" data-odd="([\\d.]*)"></div>'
    r'<div class="oddsComparisonAll__average_text" data-odd="([\\d.]*)"></div>',
    re.DOTALL,
)'''
if old_pattern_block not in content:
    raise SystemExit("ERROR: _HANDICAP_BLOCK_TEMPLATE line not found verbatim — aborting without changes.")
content = content.replace(old_pattern_block, new_pattern_block, 1)

# Append fetch_1x2_odds at the end of the file.
addition = '''

def fetch_1x2_odds(match_id: str, timeout: float = 15.0) -> Odds1X2:
    """Fetch aggregate 1X2 odds for one match via the confirmed AJAX
    endpoint (see selectors.X12_AJAX_URL_TEMPLATE) — same pattern as
    fetch_over_under_odds, no session/cookies needed.

    CONFIRMED (2026-09-14): switched to this from scraping td.table-main__odds
    directly off the daily results list page — that DOM-based approach was
    unreliable in practice (0% coverage across an entire fresh run, even
    after adding an explicit wait for the odds cells' text to populate; see
    match_list.py's history). This endpoint works instantly and reliably
    via a plain HTTP request instead, the same lesson learned earlier today
    for the hit-rate stats widget.

    Returns Odds1X2() (all None) if the request fails or the expected
    pattern isn't found — this never raises.
    """
    url = sel.X12_AJAX_URL_TEMPLATE.format(match_id=match_id)
    try:
        resp = _session.get(url, timeout=timeout)
        resp.raise_for_status()
        result = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("fetch_1x2_odds: request failed for %s: %s", url, exc)
        return Odds1X2()

    if not isinstance(result, dict) or "odds" not in result:
        return Odds1X2()

    match = _1X2_BLOCK_PATTERN.search(result["odds"])
    if not match or not all(match.groups()):
        return Odds1X2()

    try:
        home, draw, away = (float(g) for g in match.groups())
        return Odds1X2(home=home, draw=draw, away=away)
    except ValueError:
        return Odds1X2()
'''
content = content.rstrip("\n") + "\n" + addition

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Patched match_odds.py: added fetch_1x2_odds().")
PYEOF_ANDREI

python3 << 'PYEOF_ANDREI'
# ---- match_stats.py: fetch 1X2 too, return it alongside odds_ou ----
path = "betscraper/match_stats.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = '''from .match_odds import extract_match_id, fetch_over_under_odds
from .match_standings import extract_over_under_stats as _extract_hit_rate_stats
from .models import OddsOverUnder, TeamOverUnderStats

logger = logging.getLogger(__name__)


def scrape_match_stats(
    match_url: str, home_team: str, away_team: str
) -> tuple[bool, TeamOverUnderStats | None, TeamOverUnderStats | None, OddsOverUnder]:
    """Full per-match pipeline: odds + hit-rate stats. Returns
    (stats_eligible, home_stats, away_stats, odds_ou).

    CONFIRMED (2026-09-13): neither odds nor hit-rate stats need a browser
    page load at all anymore — both go through plain HTTP requests
    (match_odds.py / match_standings.py). No Selenium WebDriver is needed
    for this function; it no longer takes a `driver` argument. Selenium is
    only needed once per run now, for the initial daily match-list page
    (see match_list.py) — everything downstream of that is plain HTTP.

    stats_eligible reflects whether hit-rate stats were actually found for
    either team, consistent with the client's own definition of an eligible
    match (cup matches, single-leg ties, and friendlies have no standings
    table — see the spec PDF's "Management of non-league matches" section).
    """
    match_id = extract_match_id(match_url)
    odds_ou = fetch_over_under_odds(match_id, line=2.5) if match_id else OddsOverUnder(line=2.5)

    result = _extract_hit_rate_stats(match_url, home_team, away_team)
    if result is None:
        return False, TeamOverUnderStats(), TeamOverUnderStats(), odds_ou

    home_stats, away_stats = result
    return True, home_stats, away_stats, odds_ou'''

new = '''from .match_odds import extract_match_id, fetch_1x2_odds, fetch_over_under_odds
from .match_standings import extract_over_under_stats as _extract_hit_rate_stats
from .models import Odds1X2, OddsOverUnder, TeamOverUnderStats

logger = logging.getLogger(__name__)


def scrape_match_stats(
    match_url: str, home_team: str, away_team: str
) -> tuple[bool, TeamOverUnderStats | None, TeamOverUnderStats | None, OddsOverUnder, Odds1X2]:
    """Full per-match pipeline: odds + hit-rate stats. Returns
    (stats_eligible, home_stats, away_stats, odds_ou, odds_1x2).

    CONFIRMED (2026-09-13/14): none of odds_ou, odds_1x2, or hit-rate stats
    need a browser page load anymore — all go through plain HTTP requests
    (match_odds.py / match_standings.py). No Selenium WebDriver is needed
    for this function; it no longer takes a `driver` argument. Selenium is
    only needed once per run now, for the initial daily match-list page
    (see match_list.py) — everything downstream of that is plain HTTP.

    odds_1x2 here is fetched via AJAX (see match_odds.fetch_1x2_odds) and
    should be treated as authoritative — the list-page DOM scrape's own
    odds_1x2 attempt (match_list.py) was found unreliable (0% coverage
    across an entire fresh run) and callers should prefer this value when
    --with-stats is used.

    stats_eligible reflects whether hit-rate stats were actually found for
    either team, consistent with the client's own definition of an eligible
    match (cup matches, single-leg ties, and friendlies have no standings
    table — see the spec PDF's "Management of non-league matches" section).
    """
    match_id = extract_match_id(match_url)
    odds_ou = fetch_over_under_odds(match_id, line=2.5) if match_id else OddsOverUnder(line=2.5)
    odds_1x2 = fetch_1x2_odds(match_id) if match_id else Odds1X2()

    result = _extract_hit_rate_stats(match_url, home_team, away_team)
    if result is None:
        return False, TeamOverUnderStats(), TeamOverUnderStats(), odds_ou, odds_1x2

    home_stats, away_stats = result
    return True, home_stats, away_stats, odds_ou, odds_1x2'''

if old not in content:
    raise SystemExit("ERROR: scrape_match_stats body not found verbatim in match_stats.py — aborting without changes.")
content = content.replace(old, new, 1)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Patched match_stats.py: scrape_match_stats now also fetches and returns odds_1x2.")
PYEOF_ANDREI

python3 << 'PYEOF_ANDREI'
# ---- main.py: unpack the 5th return value and assign match.odds_1x2 ----
path = "main.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = '''                    try:
                        match, (eligible, home_stats, away_stats, odds_ou) = future.result()
                    except Exception:
                        logging.exception(
                            "[%d/%d] Failed to get stats for a match — leaving stats blank "
                            "for it and continuing with the rest.",
                            done, len(targets),
                        )
                        continue
                    match.stats_eligible = eligible
                    match.home_stats = home_stats
                    match.away_stats = away_stats
                    match.odds_ou = odds_ou'''

new = '''                    try:
                        match, (eligible, home_stats, away_stats, odds_ou, odds_1x2) = future.result()
                    except Exception:
                        logging.exception(
                            "[%d/%d] Failed to get stats for a match — leaving stats blank "
                            "for it and continuing with the rest.",
                            done, len(targets),
                        )
                        continue
                    match.stats_eligible = eligible
                    match.home_stats = home_stats
                    match.away_stats = away_stats
                    match.odds_ou = odds_ou
                    match.odds_1x2 = odds_1x2  # AJAX-fetched, more reliable than the list-page DOM scrape'''

if old not in content:
    raise SystemExit("ERROR: expected stats-loop result-unpacking block not found verbatim in main.py — aborting without changes.")
content = content.replace(old, new, 1)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Patched main.py: match.odds_1x2 now set from the AJAX-fetched value when --with-stats is used.")
PYEOF_ANDREI

echo "Verifying syntax..."
python -m py_compile betscraper/*.py main.py tools/*.py && echo "OK — syntax valid."
