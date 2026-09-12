#!/bin/bash
# Sync script: overwrites the fixed files in your Codespace checkout.
# Run from the repo root: bash sync_fixes.sh
set -e

mkdir -p "betscraper"
cat > betscraper/selectors.py << 'PYEOF_ANDREI'
"""
Every CSS selector the scraper uses, in one place.

IMPORTANT — READ THIS FIRST:
This sandbox's outbound network policy blocks betexplorer.com, so these values
could not be confirmed against the live DOM. They are best-effort defaults
based on the general BetExplorer page layout (a "table-main" style match
table, tabbed odds views, a per-match "Standings" tab). Before relying on
this scraper, run `tools/inspect_page.py <url>` from a machine that CAN reach
the site (this is Step 2 of the task, automated): it dumps every table,
tab/dropdown, and "standings"-like element it finds with its selector, so you
can paste the corrected values in here in one place.

Nothing outside this file should hard-code a selector.
"""

# ---- Date navigation (Step 3) ------------------------------------------------
# BetExplorer paginates results by day via a URL query string on the results
# page. Confirm the exact param names in DevTools > Network while clicking the
# calendar, then adjust this template. {year}/{month:02d}/{day:02d} are filled
# in by betscraper.match_list.build_date_url().
BASE_URL = "https://www.betexplorer.com"
SPORT_PATH = "/football/"
DATE_URL_TEMPLATE = BASE_URL + SPORT_PATH + "?year={year}&month={month:02d}&day={day:02d}"

# ---- Match list page (Step 4) ------------------------------------------------
MATCH_TABLE = "table.table-main"
MATCH_ROW = "table.table-main tbody tr"
LEAGUE_HEADER_ROW = "tr.table-main__head"  # section header rows that separate leagues
TEAM_HOME_CELL = "td.table-main__tt span.table-main__tt-home, td.h-text-left a"
TEAM_AWAY_CELL = "td.table-main__tt span.table-main__tt-away"
TIME_OR_STATUS_CELL = "td.table-main__time, td.h-text-center.h-text-no-wrap"
SCORE_CELL = "td.table-main__score"
ODDS_CELLS = "td.table-main__odds"
MATCH_LINK = "a"  # relative <a href> inside the row that points at the match detail page

# ---- Live / completed / scheduled detection (Step 6) -------------------------
LIVE_ROW_CLASS = "in-play"          # row or time-cell class BetExplorer uses for live matches
LIVE_TIMER_CELL = "span.min-scr"    # the running-clock element shown instead of a fixed time
COMPLETED_SCORE_PATTERN = r"^\d+:\d+$"

# ---- Odds view switch: 1X2 -> Over/Under 2.5 (Step 5) -------------------------
ODDS_VIEW_DROPDOWN = "select.js-select-odds, div.odds-type-selector"
ODDS_VIEW_OPTION_OU25 = "option[value*='over-under'], a[data-odds='ou-2.5']"

# ---- Match detail page (Steps 7-8) -------------------------------------------
STANDINGS_TABLE = "div#standings, table.table-standings"  # presence check == stats-eligible
OU_TAB_ROOT = "div#tab-over-under, div.tabs-inner"
OU_SUBTAB_1_5 = "a[data-odd='1.5'], li[data-value='1.5'] a"
OU_SUBTAB_2_5 = "a[data-odd='2.5'], li[data-value='2.5'] a"
OU_SUBTAB_3_5 = "a[data-odd='3.5'], li[data-value='3.5'] a"
OU_HOME_STATS_CELL = "table.table-over-under tbody tr:nth-child(1) td"
OU_AWAY_STATS_CELL = "table.table-over-under tbody tr:nth-child(2) td"

# ---- Overlay dismissal: age gate + cookie consent -----------------------------
# BetExplorer shows an 18+ age-verification interstitial on first load, and
# likely a cookie-consent banner on top of that — both block the match table
# from ever becoming visible/interactable, regardless of whether MATCH_ROW
# below is correct. These were NOT verified against the live site either (same
# network restriction as everything else here), so they are generic,
# broadly-compatible patterns for common consent-management frameworks
# (OneTrust, Cookiebot, Quantcast) plus a text-based fallback for a custom
# "confirm you are 18+" button. betscraper.consent.dismiss_overlays() tries
# each in turn and silently continues if none match — update/add selectors
# here once you've seen the real markup (tools/inspect_page.py --keep-open
# will show it, or just open DevTools on first load).
AGE_GATE_CONFIRM_BUTTONS = [
    "button#age-gate-confirm",
    "a#age-gate-confirm",
    ".age-verification button.confirm",
    "[data-testid='age-gate-confirm']",
]
# XPath fallback: any clickable element whose visible text matches an
# affirmative age-confirmation phrase (case-insensitive, several languages
# since betexplorer.com serves localized copy).
AGE_GATE_CONFIRM_XPATH = (
    "//button[contains(translate(text(),"
    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'18')] | "
    "//a[contains(translate(text(),"
    "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'18')]"
)

COOKIE_CONSENT_BUTTONS = [
    "#onetrust-accept-btn-handler",       # OneTrust
    ".CybotCookiebotDialogBodyButton",    # Cookiebot
    "#qc-cmp2-ui button[mode='primary']",  # Quantcast
    "button#cookie-accept",
    ".cookie-consent button.accept",
]
PYEOF_ANDREI

mkdir -p "betscraper"
cat > betscraper/consent.py << 'PYEOF_ANDREI'
from __future__ import annotations

import logging

from selenium.common.exceptions import ElementClickInterceptedException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from . import selectors as sel

logger = logging.getLogger(__name__)


def _try_click(driver: WebDriver, by: str, value: str, wait_seconds: float) -> bool:
    try:
        el = WebDriverWait(driver, wait_seconds).until(
            EC.element_to_be_clickable((by, value))
        )
    except TimeoutException:
        return False
    try:
        el.click()
    except ElementClickInterceptedException:
        # Something (another overlay) is on top of it — try a JS click as a fallback.
        driver.execute_script("arguments[0].click();", el)
    return True


def dismiss_overlays(driver: WebDriver, wait_seconds: float = 3.0) -> None:
    """Best-effort dismissal of the age-gate and cookie-consent overlays.

    Call this right after driver.get(...) and before waiting for the match
    table — both overlays can sit on top of the page and block every other
    selector from ever matching an interactable element. Every selector here
    is a guess (see selectors.py); failing to find one is not an error, so
    this never raises — it just logs and moves on.
    """
    for css in sel.AGE_GATE_CONFIRM_BUTTONS:
        if _try_click(driver, By.CSS_SELECTOR, css, wait_seconds):
            logger.info("Dismissed age gate via selector: %s", css)
            break
    else:
        if _try_click(driver, By.XPATH, sel.AGE_GATE_CONFIRM_XPATH, wait_seconds):
            logger.info("Dismissed age gate via text-match fallback.")
        else:
            logger.debug("No age-gate overlay found (or selectors are stale).")

    for css in sel.COOKIE_CONSENT_BUTTONS:
        if _try_click(driver, By.CSS_SELECTOR, css, wait_seconds):
            logger.info("Dismissed cookie-consent banner via selector: %s", css)
            break
    else:
        logger.debug("No cookie-consent banner found (or selectors are stale).")
PYEOF_ANDREI

mkdir -p "betscraper"
cat > betscraper/match_list.py << 'PYEOF_ANDREI'
from __future__ import annotations

import datetime as dt
import logging
from urllib.parse import urljoin

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from . import selectors as sel
from .consent import dismiss_overlays
from .match_state import classify_status
from .models import Match, Odds1X2, OddsOverUnder

logger = logging.getLogger(__name__)

DEFAULT_WAIT = 15


def build_date_url(date: dt.date) -> str:
    return sel.DATE_URL_TEMPLATE.format(year=date.year, month=date.month, day=date.day)


def load_date(driver: WebDriver, date: dt.date, wait_seconds: int = DEFAULT_WAIT) -> None:
    """Navigate to the match list for a given date and wait for rows to render."""
    url = build_date_url(date)
    driver.get(url)
    dismiss_overlays(driver)
    try:
        WebDriverWait(driver, wait_seconds).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, sel.MATCH_ROW))
        )
    except TimeoutException as exc:
        raise TimeoutException(
            f"No match rows found at {url} after {wait_seconds}s. This means either "
            f"(a) sel.MATCH_ROW ({sel.MATCH_ROW!r}) doesn't match this page's real "
            f"markup, (b) sel.DATE_URL_TEMPLATE doesn't produce a valid date-filtered "
            f"URL for this site, or (c) an overlay (age gate / cookie consent) is still "
            f"blocking the page and its selector needs updating in selectors.py. Run "
            f"`python tools/inspect_page.py {url!r} --keep-open` to see what's actually "
            f"on the page."
        ) from exc


def _parse_float(text: str | None) -> float | None:
    if not text:
        return None
    text = text.strip().replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _row_text(row, css: str) -> str | None:
    elements = row.find_elements(By.CSS_SELECTOR, css)
    return elements[0].text.strip() if elements and elements[0].text.strip() else None


def extract_matches_1x2(driver: WebDriver) -> list[Match]:
    """Parse the currently loaded page's match table assuming the 1X2 odds view is active."""
    matches: list[Match] = []
    current_league = ""
    rows = driver.find_elements(By.CSS_SELECTOR, sel.MATCH_ROW)

    for row in rows:
        if "table-main__head" in (row.get_attribute("class") or ""):
            current_league = row.text.strip()
            continue

        home = _row_text(row, sel.TEAM_HOME_CELL)
        away = _row_text(row, sel.TEAM_AWAY_CELL)
        if not home:
            continue  # not a match row (ad banner, spacer, etc.)

        time_text = _row_text(row, sel.TIME_OR_STATUS_CELL) or ""
        score = _row_text(row, sel.SCORE_CELL)
        status = classify_status(row)

        odds_cells = row.find_elements(By.CSS_SELECTOR, sel.ODDS_CELLS)
        odds = Odds1X2(
            home=_parse_float(odds_cells[0].text) if len(odds_cells) > 0 else None,
            draw=_parse_float(odds_cells[1].text) if len(odds_cells) > 1 else None,
            away=_parse_float(odds_cells[2].text) if len(odds_cells) > 2 else None,
        )

        link_els = row.find_elements(By.CSS_SELECTOR, sel.MATCH_LINK)
        match_url = urljoin(sel.BASE_URL, link_els[0].get_attribute("href")) if link_els else None

        matches.append(
            Match(
                league=current_league,
                home_team=home,
                away_team=away or "",
                time_text=time_text,
                status=status,
                score=score,
                match_url=match_url,
                odds_1x2=odds,
            )
        )

    return matches


def switch_to_over_under(driver: WebDriver, wait_seconds: int = DEFAULT_WAIT) -> bool:
    """Click the odds-view control to switch from 1X2 to Over/Under 2.5.

    Returns False (and leaves the page untouched) if the control isn't found —
    callers should treat that as "O/U odds unavailable for this view" rather
    than crash the whole run.
    """
    dropdowns = driver.find_elements(By.CSS_SELECTOR, sel.ODDS_VIEW_DROPDOWN)
    if not dropdowns:
        logger.warning("Odds-view dropdown not found; selector needs verifying (see selectors.py).")
        return False

    rows_before = driver.find_elements(By.CSS_SELECTOR, sel.MATCH_ROW)
    anchor = rows_before[0] if rows_before else None

    options = driver.find_elements(By.CSS_SELECTOR, sel.ODDS_VIEW_OPTION_OU25)
    if not options:
        logger.warning("Over/Under 2.5 option not found; selector needs verifying (see selectors.py).")
        return False
    options[0].click()

    try:
        if anchor is not None:
            WebDriverWait(driver, wait_seconds).until(EC.staleness_of(anchor))
        WebDriverWait(driver, wait_seconds).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, sel.MATCH_ROW))
        )
    except TimeoutException:
        logger.warning("Timed out waiting for Over/Under view to refresh.")
        return False
    return True


def extract_matches_ou(driver: WebDriver) -> dict[str, OddsOverUnder]:
    """Parse the currently loaded page's match table assuming the Over/Under 2.5 view is active.

    Returns a dict keyed the same way as Match.match_key() so results can be
    merged back onto the 1X2 list. Keyed by match_url when the row has a
    link (the common case and the stable case), falling back to the
    team/time combo otherwise — matching Match.match_key()'s own fallback.
    """
    ou_by_key: dict[str, OddsOverUnder] = {}
    rows = driver.find_elements(By.CSS_SELECTOR, sel.MATCH_ROW)

    for row in rows:
        if "table-main__head" in (row.get_attribute("class") or ""):
            continue

        home = _row_text(row, sel.TEAM_HOME_CELL)
        away = _row_text(row, sel.TEAM_AWAY_CELL)
        if not home:
            continue

        time_text = _row_text(row, sel.TIME_OR_STATUS_CELL) or ""
        link_els = row.find_elements(By.CSS_SELECTOR, sel.MATCH_LINK)
        match_url = urljoin(sel.BASE_URL, link_els[0].get_attribute("href")) if link_els else None
        key = match_url or f"{home.strip().lower()}|{(away or '').strip().lower()}|{time_text.strip()}"

        odds_cells = row.find_elements(By.CSS_SELECTOR, sel.ODDS_CELLS)
        ou_by_key[key] = OddsOverUnder(
            line=2.5,
            over=_parse_float(odds_cells[0].text) if len(odds_cells) > 0 else None,
            under=_parse_float(odds_cells[1].text) if len(odds_cells) > 1 else None,
        )

    return ou_by_key


def merge_ou_into_matches(matches: list[Match], ou_by_key: dict[str, OddsOverUnder]) -> None:
    for match in matches:
        ou = ou_by_key.get(match.match_key())
        if ou is not None:
            match.odds_ou = ou


def scrape_day(driver: WebDriver, date: dt.date) -> list[Match]:
    """Full Steps 3-6 pipeline for a single day: load page, get 1X2, switch view, get O/U, merge."""
    load_date(driver, date)
    matches = extract_matches_1x2(driver)

    if switch_to_over_under(driver):
        ou_by_key = extract_matches_ou(driver)
        merge_ou_into_matches(matches, ou_by_key)
    else:
        logger.warning("Skipping Over/Under merge for %s — view switch failed.", date)

    return matches
PYEOF_ANDREI

mkdir -p "betscraper"
cat > betscraper/match_stats.py << 'PYEOF_ANDREI'
from __future__ import annotations

import logging

from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from . import selectors as sel
from .consent import dismiss_overlays
from .models import TeamOverUnderStats

logger = logging.getLogger(__name__)

DEFAULT_WAIT = 15


def is_stats_eligible(driver: WebDriver) -> bool:
    """Step 7: a match only has Over/Under stats if its page has a standings table.

    Deliberately DOM-based rather than a competition-name heuristic ('Cup' in
    the name), since competitions like the Champions League have no
    standings table either despite not being literally a 'cup'.
    """
    return len(driver.find_elements(By.CSS_SELECTOR, sel.STANDINGS_TABLE)) > 0


def _read_cell(driver: WebDriver, css: str) -> str | None:
    elements = driver.find_elements(By.CSS_SELECTOR, css)
    return elements[0].text.strip() if elements and elements[0].text.strip() else None


def _click_and_wait_for_change(
    driver: WebDriver, tab_css: str, old_home_value: str | None, wait_seconds: int
) -> bool:
    """Click an Over/Under sub-tab and wait for the stats table content to actually change.

    Comparing against the previously read value (rather than a fixed sleep)
    is what step 8 asks for: each click re-renders the same DOM nodes, so a
    plain 'wait for element present' would pass instantly against stale text.
    """
    tabs = driver.find_elements(By.CSS_SELECTOR, tab_css)
    if not tabs:
        logger.warning("O/U sub-tab %s not found; selector needs verifying.", tab_css)
        return False
    tabs[0].click()

    try:
        WebDriverWait(driver, wait_seconds).until(
            lambda d: _read_cell(d, sel.OU_HOME_STATS_CELL) != old_home_value
            or old_home_value is None
        )
    except TimeoutException:
        logger.warning("Timed out waiting for O/U stats to refresh after clicking %s.", tab_css)
        return False
    return True


def extract_over_under_stats(
    driver: WebDriver, wait_seconds: int = DEFAULT_WAIT
) -> tuple[TeamOverUnderStats, TeamOverUnderStats]:
    """Step 8: click through Overall / 1.5, 2.5, 3.5 and read both teams' values each time."""
    home_stats = TeamOverUnderStats()
    away_stats = TeamOverUnderStats()

    baseline_home = _read_cell(driver, sel.OU_HOME_STATS_CELL)

    if _click_and_wait_for_change(driver, sel.OU_SUBTAB_1_5, None, wait_seconds):
        home_stats.over_1_5 = _read_cell(driver, sel.OU_HOME_STATS_CELL)
        away_stats.over_1_5 = _read_cell(driver, sel.OU_AWAY_STATS_CELL)
        last_home = home_stats.over_1_5
    else:
        last_home = baseline_home

    if _click_and_wait_for_change(driver, sel.OU_SUBTAB_2_5, last_home, wait_seconds):
        home_stats.over_2_5 = _read_cell(driver, sel.OU_HOME_STATS_CELL)
        away_stats.over_2_5 = _read_cell(driver, sel.OU_AWAY_STATS_CELL)
        last_home = home_stats.over_2_5
    else:
        home_stats.over_2_5 = _read_cell(driver, sel.OU_HOME_STATS_CELL)
        away_stats.over_2_5 = _read_cell(driver, sel.OU_AWAY_STATS_CELL)

    if _click_and_wait_for_change(driver, sel.OU_SUBTAB_3_5, last_home, wait_seconds):
        home_stats.over_3_5 = _read_cell(driver, sel.OU_HOME_STATS_CELL)
        away_stats.over_3_5 = _read_cell(driver, sel.OU_AWAY_STATS_CELL)
    else:
        home_stats.over_3_5 = _read_cell(driver, sel.OU_HOME_STATS_CELL)
        away_stats.over_3_5 = _read_cell(driver, sel.OU_AWAY_STATS_CELL)

    return home_stats, away_stats


def scrape_match_stats(
    driver: WebDriver, match_url: str, wait_seconds: int = DEFAULT_WAIT
) -> tuple[bool, TeamOverUnderStats | None, TeamOverUnderStats | None]:
    """Full Steps 7-8 pipeline for one match page. Returns (eligible, home_stats, away_stats)."""
    driver.get(match_url)
    try:
        WebDriverWait(driver, wait_seconds).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except TimeoutException:
        pass
    dismiss_overlays(driver)

    if not is_stats_eligible(driver):
        return False, None, None

    home_stats, away_stats = extract_over_under_stats(driver, wait_seconds)
    return True, home_stats, away_stats
PYEOF_ANDREI

mkdir -p "betscraper"
cat > betscraper/models.py << 'PYEOF_ANDREI'
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Odds1X2:
    home: Optional[float] = None
    draw: Optional[float] = None
    away: Optional[float] = None


@dataclass
class OddsOverUnder:
    line: float = 2.5
    over: Optional[float] = None
    under: Optional[float] = None


@dataclass
class TeamOverUnderStats:
    """Over/Under hit-rate values as shown on BetExplorer's per-match 'Overall' tab."""

    over_1_5: Optional[str] = None
    under_1_5: Optional[str] = None
    over_2_5: Optional[str] = None
    under_2_5: Optional[str] = None
    over_3_5: Optional[str] = None
    under_3_5: Optional[str] = None


@dataclass
class Match:
    league: str
    home_team: str
    away_team: str
    time_text: str
    status: str  # "scheduled" | "live" | "completed"
    score: Optional[str] = None
    match_url: Optional[str] = None
    odds_1x2: Odds1X2 = field(default_factory=Odds1X2)
    odds_ou: OddsOverUnder = field(default_factory=OddsOverUnder)
    stats_eligible: Optional[bool] = None
    home_stats: Optional[TeamOverUnderStats] = None
    away_stats: Optional[TeamOverUnderStats] = None

    def match_key(self) -> str:
        """Key used to merge the 1X2 table row with the Over/Under table row for the same fixture.

        Prefers match_url: it's a stable per-fixture identifier that doesn't
        change between the two page states. Falls back to
        (home, away, time_text) only when a row has no link, but that combo is
        fragile — if a match goes live between the 1X2 load and the O/U-view
        switch, its time cell can change from a fixed kickoff time to a
        running clock, silently breaking the merge for that row.
        """
        if self.match_url:
            return self.match_url
        return f"{self.home_team.strip().lower()}|{self.away_team.strip().lower()}|{self.time_text.strip()}"

    def to_flat_dict(self) -> dict:
        stats = self.home_stats or TeamOverUnderStats()
        astats = self.away_stats or TeamOverUnderStats()
        return {
            "league": self.league,
            "time": self.time_text,
            "status": self.status,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "score": self.score,
            "odds_1": self.odds_1x2.home,
            "odds_x": self.odds_1x2.draw,
            "odds_2": self.odds_1x2.away,
            "ou_line": self.odds_ou.line,
            "odds_over": self.odds_ou.over,
            "odds_under": self.odds_ou.under,
            "stats_eligible": self.stats_eligible,
            "home_over_1.5": stats.over_1_5,
            "home_under_1.5": stats.under_1_5,
            "home_over_2.5": stats.over_2_5,
            "home_under_2.5": stats.under_2_5,
            "home_over_3.5": stats.over_3_5,
            "home_under_3.5": stats.under_3_5,
            "away_over_1.5": astats.over_1_5,
            "away_under_1.5": astats.under_1_5,
            "away_over_2.5": astats.over_2_5,
            "away_under_2.5": astats.under_2_5,
            "away_over_3.5": astats.over_3_5,
            "away_under_3.5": astats.under_3_5,
            "match_url": self.match_url,
        }
PYEOF_ANDREI

mkdir -p "betscraper"
cat > betscraper/export.py << 'PYEOF_ANDREI'
from __future__ import annotations

import os

import pandas as pd

from .models import Match


def matches_to_dataframe(matches: list[Match]) -> pd.DataFrame:
    return pd.DataFrame(m.to_flat_dict() for m in matches)


def save_to_excel(matches: list[Match], path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    df = matches_to_dataframe(matches)
    df.to_excel(path, index=False, engine="openpyxl")
PYEOF_ANDREI

mkdir -p "."
cat > main.py << 'PYEOF_ANDREI'
from __future__ import annotations

import argparse
import datetime as dt
import logging
import time

from betscraper.driver import build_driver
from betscraper.export import save_to_excel
from betscraper.match_list import scrape_day
from betscraper.match_stats import scrape_match_stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape BetExplorer matches, odds, and stats.")
    parser.add_argument(
        "--date",
        default=dt.date.today().isoformat(),
        help="Date to scrape, YYYY-MM-DD (default: today).",
    )
    parser.add_argument("--output", default="output/matches.xlsx", help="Output .xlsx path.")
    parser.add_argument(
        "--with-stats",
        action="store_true",
        help="Also visit each eligible match page for Over/Under 1.5/2.5/3.5 stats (slow).",
    )
    parser.add_argument(
        "--max-matches",
        type=int,
        default=None,
        help="Limit how many matches get per-match stats scraped (for testing).",
    )
    parser.add_argument("--no-headless", action="store_true", help="Show the browser window.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    date = dt.date.fromisoformat(args.date)
    driver = build_driver(headless=not args.no_headless)
    matches: list = []

    try:
        try:
            matches = scrape_day(driver, date)
            logging.info("Found %d matches for %s.", len(matches), date)
        except Exception:
            logging.exception(
                "Failed to scrape the match list for %s — nothing to save. "
                "See the exception above for what to check in selectors.py.",
                date,
            )
            raise

        if args.with_stats:
            targets = [m for m in matches if m.match_url][: args.max_matches]
            for i, match in enumerate(targets, start=1):
                logging.info(
                    "[%d/%d] Stats for %s vs %s", i, len(targets), match.home_team, match.away_team
                )
                try:
                    eligible, home_stats, away_stats = scrape_match_stats(driver, match.match_url)
                    match.stats_eligible = eligible
                    match.home_stats = home_stats
                    match.away_stats = away_stats
                except Exception:
                    logging.exception(
                        "Failed to get stats for %s vs %s — leaving stats blank for this "
                        "match and continuing with the rest.",
                        match.home_team,
                        match.away_team,
                    )
                time.sleep(1)  # be polite between match-page navigations
    finally:
        driver.quit()
        if matches:
            save_to_excel(matches, args.output)
            logging.info("Saved %s (%d matches).", args.output, len(matches))
        else:
            logging.warning("No matches collected — nothing saved to %s.", args.output)


if __name__ == "__main__":
    main()
PYEOF_ANDREI

mkdir -p "tools"
cat > tools/inspect_page.py << 'PYEOF_ANDREI'
"""
Run this ONCE per page type (completed match, live match, scheduled match,
cup match) from a machine that can actually reach betexplorer.com — this
sandbox's network policy blocks it, so this script could not be run or
tested here.

It automates Step 2 of the task: instead of manually right-click > Inspect on
every element, it dumps every table, dropdown/tab control, and
"standings"-looking element on the page along with a CSS selector you can
paste straight into betscraper/selectors.py.

Usage:
    python tools/inspect_page.py "https://www.betexplorer.com/football/"
    python tools/inspect_page.py "https://www.betexplorer.com/football/some-match/xxxx/" --keep-open
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from selenium.common.exceptions import StaleElementReferenceException  # noqa: E402
from selenium.webdriver.support.ui import WebDriverWait  # noqa: E402

from betscraper.consent import dismiss_overlays  # noqa: E402
from betscraper.driver import build_driver  # noqa: E402


def describe(el) -> str:
    tag = el.tag_name
    el_id = el.get_attribute("id")
    classes = el.get_attribute("class")
    parts = [tag]
    if el_id:
        parts.append(f"#{el_id}")
    if classes:
        parts.append("." + ".".join(classes.split()))
    return "".join(parts)


def _wait_for_stable_dom(driver, settle_seconds: float = 1.5, timeout: float = 10.0) -> None:
    """Wait until the page's HTML length stops changing.

    BetExplorer re-renders parts of the page after initial load (odds
    ticking in, AJAX-populated tables, etc.), which turns element
    references grabbed too early into StaleElementReferenceException.
    There's no reliable single "ready" event for that, so this polls the
    document's HTML length until it's identical across two checks
    `settle_seconds` apart, up to `timeout` seconds total.
    """
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )
    deadline = time.monotonic() + timeout
    last_len = -1
    while time.monotonic() < deadline:
        current_len = len(driver.execute_script("return document.documentElement.outerHTML"))
        if current_len == last_len:
            return
        last_len = current_len
        time.sleep(settle_seconds)


def _each(elements, action) -> None:
    """Run `action(el)` for each element, skipping ones that went stale mid-loop
    instead of letting one bad element kill the whole inspection run."""
    for el in elements:
        try:
            action(el)
        except StaleElementReferenceException:
            print("  [skipped — element went stale while reading it; page is still re-rendering]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump candidate selectors from a BetExplorer page.")
    parser.add_argument("url")
    parser.add_argument("--keep-open", action="store_true", help="Leave the browser open for manual inspection.")
    args = parser.parse_args()

    driver = build_driver(headless=not args.keep_open)
    driver.get(args.url)
    dismiss_overlays(driver)
    _wait_for_stable_dom(driver)

    print(f"\n=== {args.url} ===\n")

    print("--- <table> elements (candidates for match list / standings) ---")
    _each(
        driver.find_elements("css selector", "table"),
        lambda t: print(f"  {describe(t)}  ({len(t.find_elements('css selector', 'tr'))} rows)"),
    )

    print("\n--- Elements whose id/class mentions 'standing' ---")
    _each(
        driver.find_elements(
            "xpath", "//*[contains(@id,'standing') or contains(@class,'standing')]"
        ),
        lambda el: print(f"  {describe(el)}"),
    )

    print("\n--- Elements whose id/class mentions 'live' or 'in-play' ---")
    _each(
        driver.find_elements(
            "xpath",
            "//*[contains(@class,'live') or contains(@class,'in-play') or contains(@id,'live')]",
        ),
        lambda el: print(f"  {describe(el)}"),
    )

    print("\n--- <select>/dropdown and tab-like controls (odds view switch, O/U sub-tabs) ---")
    _each(
        driver.find_elements("css selector", "select, [role='tablist'], .tabs, .tab"),
        lambda el: print(f"  {describe(el)}  text={el.text[:60]!r}"),
    )

    print("\n--- Elements with a 'data-odd' or similar data-* attribute ---")

    def _print_data_attrs(el):
        attrs = {
            k: el.get_attribute(k)
            for k in ("data-odd", "data-tab", "data-value", "data-odds")
            if el.get_attribute(k)
        }
        print(f"  {describe(el)}  {attrs}")

    _each(
        driver.find_elements(
            "xpath", "//*[@data-odd or @data-tab or @data-value or @data-odds]"
        ),
        _print_data_attrs,
    )

    print("\n--- Anchor/text nodes containing '1X2' or 'Over/Under' ---")
    _each(
        driver.find_elements(
            "xpath", "//*[contains(text(),'1X2') or contains(text(),'Over/Under')]"
        ),
        lambda el: print(f"  {describe(el)}  text={el.text[:60]!r}"),
    )

    if args.keep_open:
        input("\nBrowser left open. Press Enter here to close it...")
    driver.quit()


if __name__ == "__main__":
    main()
PYEOF_ANDREI

echo "All files synced. Verifying syntax..."
python -m py_compile betscraper/*.py main.py tools/*.py && echo "OK — syntax valid."
