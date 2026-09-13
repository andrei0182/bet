#!/bin/bash
# sync_fixes.sh — fixes load_date(): driver.get(url) and dismiss_overlays()
# were OUTSIDE the try/except block, so a timeout at the browser's own page
# load level (not just our WebDriverWait for elements) crashed the whole
# run immediately instead of being retried. Moves both inside the try block
# so every failure mode during a load attempt is covered by the retry loop.
# Run from the repo root: bash sync_fixes.sh
set -e

python3 << 'PYEOF_ANDREI'
path = "betscraper/match_list.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = '''    for attempt in range(1, retries + 1):
        driver.get(url)
        dismiss_overlays(driver)
        try:
            WebDriverWait(driver, wait_seconds).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, sel.MATCH_ROW))
            )
            return  # success
        except TimeoutException as exc:
            last_exc = exc
            logger.warning(
                "load_date attempt %d/%d timed out for %s — retrying",
                attempt, retries, url,
            )
            if attempt < retries:
                time.sleep(3)'''

new = '''    for attempt in range(1, retries + 1):
        try:
            driver.get(url)
            dismiss_overlays(driver)
            WebDriverWait(driver, wait_seconds).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, sel.MATCH_ROW))
            )
            return  # success
        except TimeoutException as exc:
            # Covers both a page-load-level timeout from driver.get() itself
            # (Chrome's own renderer taking too long) and our own
            # WebDriverWait timing out waiting for match rows to appear —
            # either way, the fix is the same: reload and try again.
            last_exc = exc
            logger.warning(
                "load_date attempt %d/%d timed out for %s — retrying",
                attempt, retries, url,
            )
            if attempt < retries:
                time.sleep(3)'''

if old not in content:
    raise SystemExit("ERROR: expected load_date retry loop not found verbatim — aborting without changes.")
content = content.replace(old, new, 1)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Patched betscraper/match_list.py: driver.get()/dismiss_overlays() now inside the retry loop's try block.")
PYEOF_ANDREI

echo "Verifying syntax..."
python -m py_compile betscraper/*.py main.py tools/*.py && echo "OK — syntax valid."
