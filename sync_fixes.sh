#!/bin/bash
# sync_fixes.sh — increases retry tolerance for 429/5xx errors in both
# match_odds.py and match_standings.py (total 4->8 attempts, backoff 1.0->2.0
# — more patience before giving up on a single match's request), and lowers
# default --workers 5->3 in main.py to reduce how hard we hammer the site
# under sustained load across thousands of matches.
# Run from the repo root: bash sync_fixes.sh
set -e

for f in betscraper/match_odds.py betscraper/match_standings.py; do
  python3 - "$f" << 'PYEOF_ANDREI'
import sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = '_retry = Retry(total=4, backoff_factor=1.0, status_forcelist=[429, 500, 502, 503, 504], respect_retry_after_header=True)'
new = '_retry = Retry(total=8, backoff_factor=2.0, status_forcelist=[429, 500, 502, 503, 504], respect_retry_after_header=True)'

if old not in content:
    raise SystemExit(f"ERROR: expected Retry(...) line not found verbatim in {path} — aborting without changes.")
content = content.replace(old, new, 1)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print(f"Patched {path}: retry total 4->8, backoff_factor 1.0->2.0.")
PYEOF_ANDREI
done

python3 << 'PYEOF_ANDREI'
path = "main.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = '''    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Concurrent threads for --with-stats' per-match HTTP requests (default: 5 — "
        "higher values risk 429 Too Many Requests from the site).",
    )'''
new = '''    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="Concurrent threads for --with-stats' per-match HTTP requests (default: 3 — "
        "higher values risk 429 Too Many Requests from the site under sustained load).",
    )'''
if old not in content:
    raise SystemExit("ERROR: --workers arg block not found verbatim in main.py — aborting without changes.")
content = content.replace(old, new, 1)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Patched main.py: default --workers 5 -> 3.")
PYEOF_ANDREI

echo "Verifying syntax..."
python -m py_compile betscraper/*.py main.py tools/*.py && echo "OK — syntax valid."
