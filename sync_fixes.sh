#!/bin/bash
# sync_fixes.sh — fixes a critical bug from the last run: 429 Too Many
# Requests errors under 10-way concurrency were being cached PERMANENTLY as
# "this league has no standings data", poisoning every match in that league
# for the rest of the run (16/1263 stats_eligible, 63/1263 odds — the real
# failure rate was much lower than that number suggests). Adds automatic
# retry-with-backoff for 429/5xx at the HTTP layer (handles most transient
# errors invisibly) and stops caching a lookup as a permanent negative when
# it failed due to a request/network error rather than a genuinely missing
# ts token. Also drops default concurrency 10 -> 5 to be less aggressive.
# Run from the repo root: bash sync_fixes.sh
set -e

python3 << 'PYEOF_ANDREI'
# ---- match_odds.py: add retry adapter ----
path = "betscraper/match_odds.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = '''import requests

from . import selectors as sel
from .models import OddsOverUnder

logger = logging.getLogger(__name__)'''
new = '''import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import selectors as sel
from .models import OddsOverUnder

logger = logging.getLogger(__name__)'''
if old not in content:
    raise SystemExit("ERROR: match_odds.py import block not found verbatim — aborting without changes.")
content = content.replace(old, new, 1)

old_session = '''_session = requests.Session()
_session.headers.update({"User-Agent": _USER_AGENT, "X-Requested-With": "XMLHttpRequest"})'''
new_session = '''_session = requests.Session()
_session.headers.update({"User-Agent": _USER_AGENT, "X-Requested-With": "XMLHttpRequest"})
_retry = Retry(total=4, backoff_factor=1.0, status_forcelist=[429, 500, 502, 503, 504], respect_retry_after_header=True)
_session.mount("https://", HTTPAdapter(max_retries=_retry))
_session.mount("http://", HTTPAdapter(max_retries=_retry))'''
if old_session not in content:
    raise SystemExit("ERROR: match_odds.py session block not found verbatim — aborting without changes.")
content = content.replace(old_session, new_session, 1)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Patched match_odds.py: added retry-with-backoff for 429/5xx.")
PYEOF_ANDREI

python3 << 'PYEOF_ANDREI'
# ---- match_standings.py: add retry adapter + stop caching transient failures ----
path = "betscraper/match_standings.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old_import = "import requests"
new_import = '''import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry'''
if old_import not in content:
    raise SystemExit("ERROR: match_standings.py import block not found verbatim — aborting without changes.")
content = content.replace(old_import, new_import, 1)

old_session = '''_session = requests.Session()
_session.headers.update({"User-Agent": _USER_AGENT, "X-Requested-With": "XMLHttpRequest"})'''
new_session = '''_session = requests.Session()
_session.headers.update({"User-Agent": _USER_AGENT, "X-Requested-With": "XMLHttpRequest"})
_retry = Retry(total=4, backoff_factor=1.0, status_forcelist=[429, 500, 502, 503, 504], respect_retry_after_header=True)
_session.mount("https://", HTTPAdapter(max_retries=_retry))
_session.mount("http://", HTTPAdapter(max_retries=_retry))'''
if old_session not in content:
    raise SystemExit("ERROR: match_standings.py session block not found verbatim — aborting without changes.")
content = content.replace(old_session, new_session, 1)

# discover_ts_token / fetch_league_over_under_html: let RequestException
# propagate instead of swallowing it into a None return, so get_league_stats
# can tell "transient failure" apart from "genuinely no ts token".
old_discover = '''def discover_ts_token(league_base_url: str, timeout: float = 10.0) -> str | None:
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
    return match.group(1) if match else None'''
new_discover = '''def discover_ts_token(league_base_url: str, timeout: float = 10.0) -> str | None:
    """Plain GET of the league's own page — the `ts` token is right there in
    the server-rendered HTML, no browser/JS execution needed.

    Raises requests.RequestException on a network/HTTP failure (after the
    session's own retry-with-backoff is exhausted) — callers should NOT
    treat that the same as a successfully-fetched page with no token; see
    get_league_stats for why that distinction matters (cache poisoning).
    """
    resp = _session.get(league_base_url, timeout=timeout)
    resp.raise_for_status()
    match = _TS_PATTERN.search(resp.text)
    return match.group(1) if match else None'''
if old_discover not in content:
    raise SystemExit("ERROR: discover_ts_token not found verbatim — aborting without changes.")
content = content.replace(old_discover, new_discover, 1)

old_fetch = '''def fetch_league_over_under_html(league_base_url: str, timeout: float = 15.0) -> str | None:
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
    return resp.text'''
new_fetch = '''def fetch_league_over_under_html(league_base_url: str, timeout: float = 15.0) -> str | None:
    """Raises requests.RequestException on a network/HTTP failure — see
    discover_ts_token's docstring for why callers must not conflate that
    with a real negative (returns None only for a successfully-fetched page
    with no ts token in it)."""
    ts = discover_ts_token(league_base_url, timeout=timeout)
    if not ts:
        return None
    url = f"{league_base_url}standings/?table=over_under&table_sub=overall&ts={ts}&dcheck=0&as-ajax=1&l=en"
    resp = _session.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text'''
if old_fetch not in content:
    raise SystemExit("ERROR: fetch_league_over_under_html not found verbatim — aborting without changes.")
content = content.replace(old_fetch, new_fetch, 1)

# get_league_stats: only cache a PERMANENT None for a genuine "fetched fine,
# no token/data" negative. A transient RequestException (even after the
# session's own retries are exhausted) releases the pending slot instead of
# poisoning the league for the rest of the run.
old_get = '''    html = fetch_league_over_under_html(league_base_url)
    if not html:
        with _league_cache_lock:
            _league_cache[league_base_url] = None
        return None'''
new_get = '''    try:
        html = fetch_league_over_under_html(league_base_url)
    except requests.RequestException as exc:
        logger.warning(
            "get_league_stats: transient failure for %s: %s — not caching as a "
            "permanent negative, a later match from this league will retry",
            league_base_url, exc,
        )
        with _league_cache_lock:
            _league_cache.pop(league_base_url, None)
        return None

    if not html:
        with _league_cache_lock:
            _league_cache[league_base_url] = None
        return None'''
if old_get not in content:
    raise SystemExit("ERROR: get_league_stats fetch block not found verbatim — aborting without changes.")
content = content.replace(old_get, new_get, 1)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Patched match_standings.py: added retry-with-backoff, stopped caching transient failures as permanent negatives.")
PYEOF_ANDREI

python3 << 'PYEOF_ANDREI'
# ---- main.py: default workers 10 -> 5 ----
path = "main.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = '''    parser.add_argument(
        "--workers",
        type=int,
        default=10,
        help="Concurrent threads for --with-stats' per-match HTTP requests (default: 10).",
    )'''
new = '''    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Concurrent threads for --with-stats' per-match HTTP requests (default: 5 — "
        "higher values risk 429 Too Many Requests from the site).",
    )'''
if old not in content:
    raise SystemExit("ERROR: --workers arg block not found verbatim in main.py — aborting without changes.")
content = content.replace(old, new, 1)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Patched main.py: default --workers 10 -> 5.")
PYEOF_ANDREI

echo "Verifying syntax..."
python -m py_compile betscraper/*.py main.py tools/*.py && echo "OK — syntax valid."
