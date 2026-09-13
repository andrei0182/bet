#!/bin/bash
# sync_fixes.sh — shortens the ts-token wait/retry budget in
# match_standings.py. The standings widget is unreliable at scale (observed
# not appearing even after 60-90s on multiple matches/leagues) — waiting
# that long per match would make a full day's run impractically slow.
# Fails fast instead: 2 short attempts (8s each, ~16s max) rather than 3
# long ones (20s each, ~60s max). Per-team stats will simply stay blank
# more often, which the pipeline already handles as a normal outcome.
# Run from the repo root: bash sync_fixes.sh
set -e

python3 << 'PYEOF_ANDREI'
path = "betscraper/match_standings.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

replacements = [
    (
        'def discover_ts_token(driver: WebDriver, wait_seconds: float = 20.0) -> str | None:',
        'def discover_ts_token(driver: WebDriver, wait_seconds: float = 8.0) -> str | None:',
    ),
    (
        '    wait_seconds: float = 20.0,\n    retries: int = 3,\n) -> tuple["TeamOverUnderStats", "TeamOverUnderStats"] | None:',
        '    wait_seconds: float = 8.0,\n    retries: int = 2,\n) -> tuple["TeamOverUnderStats", "TeamOverUnderStats"] | None:',
    ),
]

for old, new in replacements:
    if old not in content:
        raise SystemExit(f"ERROR: expected text not found verbatim:\n{old!r}\nAborting without changes.")
    content = content.replace(old, new, 1)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Patched betscraper/match_standings.py: ts-token wait reduced to 2 attempts x 8s (~16s max per match, down from ~60s).")
PYEOF_ANDREI

echo "Verifying syntax..."
python -m py_compile betscraper/*.py main.py tools/*.py && echo "OK — syntax valid."
