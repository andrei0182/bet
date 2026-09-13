#!/bin/bash
# sync_fixes.sh — MAJOR REWRITE: replaces the Selenium-based Over/Under
# hit-rate stats pipeline with plain HTTP requests, confirmed to work
# reliably and instantly via curl where Selenium/Chrome consistently failed
# or took 60-90s+ (same content, same ts token, same endpoint — the
# bottleneck was specific to the Selenium/Chrome pipeline in this
# environment, not the site or the data). Also switches from per-match to
# per-league fetching with caching: the Over/Under hit-rate data is a
# league-wide table anyway, so one request per league now serves every
# match in that league for the whole run, instead of one Selenium page
# load per match.
# Run from the repo root: bash sync_fixes.sh
set -e

pip install --quiet requests --break-system-packages 2>/dev/null || pip install --quiet requests

cat > betscraper/match_standings.py << 'PYEOF_ANDREI'
from __future__ import annotations

import logging
import re

import requests

logger = logging.getLogger(__name__)

# ---- Confirmed (2026-09-13), via curl (NOT Selenium — see note below) -------
# Per-team Over/Under hit-rate stats live on a LEAGUE/SEASON standings AJAX
# endpoint:
#   {league_base_url}standings/?table=over_under&table_sub=overall&ts={ts}
#       &dcheck=0&as-ajax=1&l=en
# where league_base_url is the match URL with its last two path segments
# (match-slug/match-id/) stripped, e.g.
#   https://www.betexplorer.com/football/england/premier-league/
# The `ts` session token is server-rendered directly in that league page's
# raw HTML (in the Standings section's tab links) — a plain GET with a
# browser-like User-Agent returns it instantly, confirmed via curl.
#
# CRITICAL: don't fetch this via Selenium/Chrome. Extensive testing
# (2026-09-13) across ~10 different matches, multiple leagues (including
# Premier League), headless and non-headless Chrome, and three different
# in-page interaction strategies (raw page_source polling, DOM element
# waiting, and clicking the real "Over/Under" tab) ALL failed consistently
# — the token/widget did not appear within 60-90s in Chrome even though the
# exact same content is available instantly via a plain HTTP GET (confirmed
# via curl from the same machine/network in under a second). The bottleneck
# is specific to the Selenium/Chrome pipeline in this environment (likely
# anti-automation handling or simply how that particular async widget
# renders in a scripted browser), not the site's data or this ts/endpoint
# approach — don't waste time re-adding a Selenium-based path here.
#
# The response HTML contains one <div id="box-table-type-6-{line}"> per O/U
# line (0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5), each with a full league table:
# every team's name, matches played, Over count, Under count. Since this is
# a league-wide table (not per-match), fetch once per league and cache —
# every match in that league during this run reuses the same fetch.
_TS_PATTERN = re.compile(r"[?&]ts=([A-Za-z0-9]+)")
_TEAM_ROW_PATTERN = re.compile(
    r"getUrlByWinType\('/football/team/[^/]+/[A-Za-z0-9]+/'\);\">([^<]+)</a>.*?"
    r'<td class="matches_played col_matches_played">(\d+)</td>\s*'
    r'<td class="over col_over">(\d+)</td>\s*'
    r'<td class="under col_under">(\d+)</td>',
    re.DOTALL,
)
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_session = requests.Session()
_session.headers.update({"User-Agent": _USER_AGENT, "X-Requested-With": "XMLHttpRequest"})

# league_base_url -> {team_name_lower: {line: (matches_played, over, under)}}, or None on failure
_league_cache: dict[str, dict[str, dict[float, tuple[int, int, int]]] | None] = {}


def build_league_base_url(match_url: str) -> str:
    """Strip the match-slug/match-id/ tail off a confirmed match URL to get
    the league/season base URL, e.g.
    "https://www.betexplorer.com/football/england/premier-league/lille-troyes/EVVF4G0T/"
    -> "https://www.betexplorer.com/football/england/premier-league/"
    """
    trimmed = match_url.rstrip("/")
    base, _match_slug, _match_id = trimmed.rsplit("/", 2)
    return base + "/"


def discover_ts_token(league_base_url: str, timeout: float = 10.0) -> str | None:
    """Plain GET of the league's own page — the `ts` token is right there in
    the server-rendered HTML, no browser/JS execution needed.
    """
    try:
        resp = _session.get(league_base_url, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("discover_ts_token: request failed for %s: %s", league_base_url, exc)
        return None
    match = _TS_PATTERN.search(resp.text)
    return match.group(1) if match else None


def fetch_league_over_under_html(league_base_url: str, timeout: float = 15.0) -> str | None:
    ts = discover_ts_token(league_base_url, timeout=timeout)
    if not ts:
        return None
    url = f"{league_base_url}standings/?table=over_under&table_sub=overall&ts={ts}&dcheck=0&as-ajax=1&l=en"
    try:
        resp = _session.get(url, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("fetch_league_over_under_html: request failed for %s: %s", url, exc)
        return None
    return resp.text


def parse_all_teams_for_line(html: str, line: float) -> dict[str, tuple[int, int, int]]:
    """Returns {team_name_lower: (matches_played, over, under)} for every
    team in one O/U line's box within the full league response.
    """
    line_key = f"{line:g}"
    if "." not in line_key:
        line_key = f"{line:.1f}"
    box_start = html.find(f'id="box-table-type-6-{line_key}"')
    if box_start == -1:
        return {}
    box_end = html.find(f'id="last_updated_box-table-type-6-{line_key}"', box_start)
    box_html = html[box_start : box_end if box_end != -1 else None]

    result: dict[str, tuple[int, int, int]] = {}
    for match in _TEAM_ROW_PATTERN.finditer(box_html):
        team_name, matches_played, over, under = match.groups()
        result[team_name.strip().lower()] = (int(matches_played), int(over), int(under))
    return result


def get_league_stats(
    match_url: str, lines: tuple[float, ...] = (1.5, 2.5, 3.5)
) -> dict[str, dict[float, tuple[int, int, int]]] | None:
    """Fetch (once per league, cached for the rest of this run) every team's
    hit-rate stats for the given O/U lines. Returns None if the league's
    standings couldn't be fetched at all (e.g. genuinely no standings for
    this competition, or a request failure) — failures are cached too, so a
    broken league is only retried once per run, not once per match.
    """
    league_base_url = build_league_base_url(match_url)
    if league_base_url in _league_cache:
        return _league_cache[league_base_url]

    html = fetch_league_over_under_html(league_base_url)
    if not html:
        _league_cache[league_base_url] = None
        return None

    teams: dict[str, dict[float, tuple[int, int, int]]] = {}
    for line in lines:
        for team_name_lower, stats in parse_all_teams_for_line(html, line).items():
            teams.setdefault(team_name_lower, {})[line] = stats

    _league_cache[league_base_url] = teams
    return teams


def extract_over_under_stats(
    match_url: str,
    home_team: str,
    away_team: str,
    lines: tuple[float, ...] = (1.5, 2.5, 3.5),
) -> tuple["TeamOverUnderStats", "TeamOverUnderStats"] | None:
    """Look up both teams' hit-rate stats for the given O/U lines, from the
    (cached) league-wide table. Returns None if the league's stats couldn't
    be fetched at all, or neither team was found in them (e.g. a genuine
    name mismatch, or a cup competition with no standings table).
    """
    from .models import TeamOverUnderStats  # local import to avoid a cycle at module load

    league_stats = get_league_stats(match_url, lines=lines)
    if league_stats is None:
        return None

    home_data = league_stats.get(home_team.strip().lower())
    away_data = league_stats.get(away_team.strip().lower())
    if not home_data and not away_data:
        return None

    home_stats = TeamOverUnderStats()
    away_stats = TeamOverUnderStats()
    found_any = False
    for line in lines:
        line_key = f"{line:.1f}".replace(".", "_")
        if home_data and line in home_data:
            _matches, over, under = home_data[line]
            setattr(home_stats, f"over_{line_key}", str(over))
            setattr(home_stats, f"under_{line_key}", str(under))
            found_any = True
        if away_data and line in away_data:
            _matches, over, under = away_data[line]
            setattr(away_stats, f"over_{line_key}", str(over))
            setattr(away_stats, f"under_{line_key}", str(under))
            found_any = True

    return (home_stats, away_stats) if found_any else None
PYEOF_ANDREI

cat > betscraper/match_stats.py << 'PYEOF_ANDREI'
from __future__ import annotations

import logging

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait

from .consent import dismiss_overlays
from .match_odds import extract_match_id, fetch_over_under_odds
from .match_standings import extract_over_under_stats as _extract_hit_rate_stats
from .models import OddsOverUnder, TeamOverUnderStats

logger = logging.getLogger(__name__)

DEFAULT_WAIT = 15


def scrape_match_stats(
    driver: WebDriver, match_url: str, home_team: str, away_team: str, wait_seconds: int = DEFAULT_WAIT
) -> tuple[bool, TeamOverUnderStats | None, TeamOverUnderStats | None, OddsOverUnder]:
    """Full per-match pipeline for one match page. Returns (stats_eligible,
    home_stats, away_stats, odds_ou).

    odds_ou still goes through the browser session (Selenium execute_async_script)
    since it needs the match page's own cookies/context and doesn't need a ts
    token. Hit-rate stats (home_stats/away_stats) now go through plain HTTP
    requests instead (see match_standings.py) — confirmed far faster and more
    reliable than the Selenium-based approach it replaces; driver is no
    longer needed for that part at all.

    stats_eligible reflects whether hit-rate stats were actually found for
    either team, consistent with the client's own definition of an eligible
    match (cup matches, single-leg ties, and friendlies have no standings
    table — see the spec PDF's "Management of non-league matches" section).
    """
    driver.get(match_url)
    try:
        WebDriverWait(driver, wait_seconds).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except TimeoutException:
        pass
    dismiss_overlays(driver)

    match_id = extract_match_id(match_url)
    odds_ou = fetch_over_under_odds(driver, match_id, line=2.5) if match_id else OddsOverUnder(line=2.5)

    result = _extract_hit_rate_stats(match_url, home_team, away_team)
    if result is None:
        return False, TeamOverUnderStats(), TeamOverUnderStats(), odds_ou

    home_stats, away_stats = result
    return True, home_stats, away_stats, odds_ou
PYEOF_ANDREI

python3 << 'PYEOF_ANDREI'
path = "requirements.txt"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()
if "requests" not in content:
    if not content.endswith("\n"):
        content += "\n"
    content += "requests>=2.31\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Added requests>=2.31 to requirements.txt")
else:
    print("requests already in requirements.txt")
PYEOF_ANDREI

echo "Verifying syntax..."
python -m py_compile betscraper/*.py main.py tools/*.py && echo "OK — syntax valid."
