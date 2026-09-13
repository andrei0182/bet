#!/bin/bash
# sync_fixes.sh — fixes a regression: 1X2 odds cells (td.table-main__odds)
# exist in the DOM as soon as match rows appear, but their TEXT populates
# asynchronously slightly later (documented in selectors.py's ODDS_CELLS
# comment). load_date's WebDriverWait only waited for row presence, not for
# odds text — on a fast page load, extraction read the cells before their
# text rendered, silently returning None for every match's 1X2 odds.
# Adds a short additional wait for at least one odds cell to have non-empty
# text before proceeding, bounded so it doesn't hang if a page genuinely
# has no odds populated at all.
# Run from the repo root: bash sync_fixes.sh
set -e

python3 << 'PYEOF_ANDREI'
path = "betscraper/match_list.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = '''            driver.get(url)
            dismiss_overlays(driver)
            WebDriverWait(driver, wait_seconds).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, sel.MATCH_ROW))
            )
            return  # success'''

new = '''            driver.get(url)
            dismiss_overlays(driver)
            WebDriverWait(driver, wait_seconds).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, sel.MATCH_ROW))
            )
            _wait_for_odds_text(driver)
            return  # success'''

if old not in content:
    raise SystemExit("ERROR: expected load_date success block not found verbatim — aborting without changes.")
content = content.replace(old, new, 1)

# Insert the helper right before load_date's definition.
anchor = "def load_date(driver: WebDriver, date: dt.date, wait_seconds: int = DEFAULT_WAIT, retries: int = 3) -> None:"
helper = '''def _wait_for_odds_text(driver: WebDriver, settle_seconds: float = 8.0) -> None:
    """Match rows (and their odds <td> cells) appear in the DOM as soon as
    presence_of_element_located(MATCH_ROW) succeeds, but the odds cells'
    TEXT populates asynchronously slightly after that (see ODDS_CELLS'
    comment in selectors.py) — on a fast page load, reading them
    immediately silently returns empty/None for every match's 1X2 odds.
    Waits for at least one odds cell to have non-empty text as a signal
    that rendering has caught up. Bounded and non-fatal: if the page
    genuinely has no odds populated yet for any match (e.g. a date far
    enough in the future that no bookmaker has posted odds), this times
    out quietly and extraction proceeds anyway rather than retrying the
    whole page load forever.
    """
    try:
        WebDriverWait(driver, settle_seconds).until(
            lambda d: any(
                el.text.strip() for el in d.find_elements(By.CSS_SELECTOR, sel.ODDS_CELLS)
            )
        )
    except TimeoutException:
        logger.info(
            "_wait_for_odds_text: no odds cell text appeared within %.0fs — "
            "proceeding anyway (may be a date with no odds posted yet)",
            settle_seconds,
        )


'''
if anchor not in content:
    raise SystemExit("ERROR: load_date anchor not found verbatim — aborting without changes.")
content = content.replace(anchor, helper + anchor, 1)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Patched betscraper/match_list.py: load_date now waits for odds cell text to populate before extraction.")
PYEOF_ANDREI

echo "Verifying syntax..."
python -m py_compile betscraper/*.py main.py tools/*.py && echo "OK — syntax valid."
