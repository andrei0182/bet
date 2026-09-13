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

    CAVEAT found on match-detail sub-pages (1x2/, over-under/, etc.): if
    content is lazy-loaded only once its container scrolls into view
    (IntersectionObserver pattern), the page can look "stable" immediately
    in its empty state and this function returns too early, before
    anything ever loads. Pair this with a scroll trigger (see main()'s
    --extra-wait handling) on those pages.
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


def _scroll_and_settle(driver, extra_wait: float) -> None:
    """Scroll through the page (to trigger IntersectionObserver-based lazy
    loading) and wait `extra_wait` seconds for any resulting content to
    render, then re-run the stability wait."""
    driver.execute_script(
        "window.scrollTo(0, document.body.scrollHeight / 2);"
    )
    time.sleep(extra_wait / 2)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(extra_wait / 2)
    _wait_for_stable_dom(driver)


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
    parser.add_argument(
        "--max-rows",
        type=int,
        default=15,
        help="How many <tr> rows inside table.table-main to dump cell-by-cell (default: 15).",
    )
    parser.add_argument(
        "--find",
        default=None,
        help="Instead of dumping the first --max-rows rows, search all rows for one whose "
        "team-cell text contains this substring (case-insensitive) and dump only that row's "
        "full outerHTML plus its immediate siblings (previous/next row) for context. Useful "
        "for hunting down a specific live match instead of scrolling through hundreds of rows.",
    )
    parser.add_argument(
        "--search-source",
        default=None,
        help="Search the FULL page source (not just table rows) for this substring "
        "(case-sensitive) and print up to 5 matches with ~200 chars of surrounding "
        "context each. Useful for finding tokens/IDs embedded in <script> tags or "
        "onclick attributes rather than visible table cells.",
    )
    parser.add_argument(
        "--extra-wait",
        type=float,
        default=0.0,
        help="Seconds to scroll through the page and wait for lazy-loaded content (odds/stats "
        "widgets that only render once scrolled into view) before inspecting. Try 6-10 on "
        "match-detail sub-pages (1x2/, over-under/, etc.) that come back empty otherwise.",
    )
    parser.add_argument(
        "--click-text",
        default=None,
        help="After loading --url, find a link/element whose visible text matches this "
        "(case-insensitive substring) and click it before inspecting — simulates in-app "
        "navigation (e.g. clicking the 'O/U' tab) instead of a direct deep link, in case the "
        "site only hydrates content when navigated to client-side. Waits --extra-wait "
        "(default 5s if not set) after clicking.",
    )
    args = parser.parse_args()

    driver = build_driver(headless=not args.keep_open)
    driver.get(args.url)
    dismiss_overlays(driver)
    _wait_for_stable_dom(driver)
    if args.extra_wait > 0:
        _scroll_and_settle(driver, args.extra_wait)

    if args.click_text:
        needle = args.click_text.lower()
        candidates = driver.find_elements("css selector", "a")
        target = None
        for el in candidates:
            try:
                if needle in el.text.lower():
                    target = el
                    break
            except StaleElementReferenceException:
                continue
        if target is None:
            print(f"\n--- --click-text {args.click_text!r}: no matching link found, proceeding without clicking ---")
        else:
            print(f"\n--- Clicking link with text {target.text!r} (href={target.get_attribute('href')!r}) ---")
            driver.execute_script("arguments[0].click();", target)
            time.sleep(args.extra_wait if args.extra_wait > 0 else 5.0)
            _wait_for_stable_dom(driver)

    print(f"\n=== {args.url} ===\n")

    if args.search_source:
        print(f"--- Searching full page source for {args.search_source!r} ---")
        source = driver.page_source
        needle = args.search_source
        start = 0
        found = 0
        while found < 5:
            idx = source.find(needle, start)
            if idx == -1:
                break
            lo = max(0, idx - 100)
            hi = min(len(source), idx + len(needle) + 100)
            print(f"\n  ...{source[lo:hi]}...")
            start = idx + len(needle)
            found += 1
        if found == 0:
            print(f"  Not found anywhere in page source.")

    print("\n--- Links to team profile pages (href*='/football/team/' or onclick*='getUrlByWinType') ---")
    _each(
        driver.find_elements(
            "xpath",
            "//a[contains(@href,'/football/team/') or contains(@onclick,'getUrlByWinType')]",
        ),
        lambda el: print(
            f"  {describe(el)}  text={el.text[:40]!r}  href={el.get_attribute('href')!r}  onclick={el.get_attribute('onclick')!r}"
        ),
    )

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

    print(f"\n--- Row/cell structure: first {args.max_rows} <tr> inside table.table-main ---")

    def _print_row(idx, row):
        row_class = row.get_attribute("class") or ""
        cells = row.find_elements("css selector", "td, th")
        cell_descs = []
        for cell in cells:
            text = (cell.text or "").strip().replace("\n", " ")[:20]
            links = cell.find_elements("css selector", "a")
            href = links[0].get_attribute("href") if links else None
            cell_descs.append(
                f"[{describe(cell)} text={text!r}"
                + (f" href={href!r}" if href else "")
                + "]"
            )
        print(f"  row#{idx} class={row_class!r} tag={row.tag_name}")
        for cd in cell_descs:
            print(f"      {cd}")

    if args.find:
        print(f"\n--- Searching all rows for team text containing {args.find!r} ---")
        all_rows = driver.find_elements("css selector", "table.table-main tr")
        needle = args.find.lower()
        found_any = False
        for i, row in enumerate(all_rows):
            try:
                text = row.text.lower()
            except StaleElementReferenceException:
                continue
            if needle in text:
                found_any = True
                print(f"\n  Match at row index {i}: {row.get_attribute('outerHTML')}")
                if i > 0:
                    try:
                        print(f"\n  Previous row (index {i - 1}, for league context): {all_rows[i - 1].get_attribute('outerHTML')}")
                    except StaleElementReferenceException:
                        pass
        if not found_any:
            print(f"  No row found containing {args.find!r}.")
        if args.keep_open:
            input("\nBrowser left open. Press Enter here to close it...")
        driver.quit()
        return

    rows = driver.find_elements("css selector", "table.table-main tr")[: args.max_rows]
    for i, row in enumerate(rows):
        try:
            _print_row(i, row)
        except StaleElementReferenceException:
            print(f"  row#{i} [skipped — went stale]")

    print("\n--- Raw outerHTML of one td.table-main__tt (team/time cell) ---")
    tt_cells = driver.find_elements("css selector", "td.table-main__tt")
    if tt_cells:
        print(" ", tt_cells[0].get_attribute("outerHTML"))
    else:
        print("  (none found)")

    print("\n--- Raw outerHTML of one td.table-main__odds (odds cell) ---")
    odds_cells = driver.find_elements("css selector", "td.table-main__odds")
    if odds_cells:
        print(" ", odds_cells[0].get_attribute("outerHTML"))
    else:
        print("  (none found)")

    if args.keep_open:
        input("\nBrowser left open. Press Enter here to close it...")
    driver.quit()


if __name__ == "__main__":
    main()
