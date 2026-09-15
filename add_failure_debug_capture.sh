#!/bin/bash
# add_failure_debug_capture.sh — [bet repo] on the FINAL load_date failure
# (after all retries exhausted), saves a screenshot + the raw page HTML to
# disk before raising, so we can see exactly what BetExplorer served to
# the failing environment (blocked/challenge page vs. genuinely empty vs.
# something else) instead of guessing.
# Run from the bet repo root: bash add_failure_debug_capture.sh
set -e

python3 << 'PYEOF_ANDREI'
path = "betscraper/match_list.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = '''    raise TimeoutException(
        f"No match rows found at {url} after {retries} attempts ({wait_seconds}s each). "
        f"This means either (a) sel.MATCH_ROW ({sel.MATCH_ROW!r}) doesn't match this "
        f"page's real markup, (b) sel.DATE_URL_TEMPLATE doesn't produce a valid "
        f"date-filtered URL for this site, or (c) an overlay (age gate / cookie consent) "
        f"is still blocking the page and its selector needs updating in selectors.py. "
        f"Run `python tools/inspect_page.py {url!r} --keep-open` to see what's actually "
        f"on the page."
    ) from last_exc'''

new = '''    debug_dir = os.environ.get("BETSCRAPER_DEBUG_DIR", ".")
    os.makedirs(debug_dir, exist_ok=True)
    html_path = os.path.join(debug_dir, "load_date_failure.html")
    png_path = os.path.join(debug_dir, "load_date_failure.png")
    try:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        driver.save_screenshot(png_path)
        logger.warning("Saved failure debug artifacts to %s and %s", html_path, png_path)
    except Exception:
        logger.exception("Could not save failure debug artifacts (page may have already navigated away).")

    raise TimeoutException(
        f"No match rows found at {url} after {retries} attempts ({wait_seconds}s each). "
        f"This means either (a) sel.MATCH_ROW ({sel.MATCH_ROW!r}) doesn't match this "
        f"page's real markup, (b) sel.DATE_URL_TEMPLATE doesn't produce a valid "
        f"date-filtered URL for this site, or (c) an overlay (age gate / cookie consent) "
        f"is still blocking the page and its selector needs updating in selectors.py, or "
        f"(d) the site is blocking/challenging this environment's IP specifically. "
        f"See {html_path} and {png_path} for exactly what was served. "
        f"Run `python tools/inspect_page.py {url!r}` locally to compare against a working environment."
    ) from last_exc'''

if old not in content:
    raise SystemExit("ERROR: expected raise TimeoutException block not found verbatim — aborting without changes.")
content = content.replace(old, new, 1)

if "\nimport os\n" not in content and not content.startswith("import os\n"):
    # Add the os import alongside the existing imports at the top of the file.
    import re
    match = re.search(r"^import \w+\n", content, re.MULTILINE)
    if not match:
        raise SystemExit("ERROR: could not find a place to add 'import os' — aborting without changes.")
    insert_at = match.start()
    content = content[:insert_at] + "import os\n" + content[insert_at:]

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Patched betscraper/match_list.py: saves a screenshot + page HTML on final load_date failure.")
PYEOF_ANDREI

echo "Verifying syntax..."
python3 -c "import ast; ast.parse(open('betscraper/match_list.py').read())" && echo "OK -- syntax valid."
