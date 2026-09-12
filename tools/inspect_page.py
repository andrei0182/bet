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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump candidate selectors from a BetExplorer page.")
    parser.add_argument("url")
    parser.add_argument("--keep-open", action="store_true", help="Leave the browser open for manual inspection.")
    args = parser.parse_args()

    driver = build_driver(headless=not args.keep_open)
    driver.get(args.url)

    print(f"\n=== {args.url} ===\n")

    print("--- <table> elements (candidates for match list / standings) ---")
    for t in driver.find_elements("css selector", "table"):
        rows = t.find_elements("css selector", "tr")
        print(f"  {describe(t)}  ({len(rows)} rows)")

    print("\n--- Elements whose id/class mentions 'standing' ---")
    for el in driver.find_elements(
        "xpath", "//*[contains(@id,'standing') or contains(@class,'standing')]"
    ):
        print(f"  {describe(el)}")

    print("\n--- Elements whose id/class mentions 'live' or 'in-play' ---")
    for el in driver.find_elements(
        "xpath",
        "//*[contains(@class,'live') or contains(@class,'in-play') or contains(@id,'live')]",
    ):
        print(f"  {describe(el)}")

    print("\n--- <select>/dropdown and tab-like controls (odds view switch, O/U sub-tabs) ---")
    for el in driver.find_elements("css selector", "select, [role='tablist'], .tabs, .tab"):
        print(f"  {describe(el)}  text={el.text[:60]!r}")

    print("\n--- Elements with a 'data-odd' or similar data-* attribute ---")
    for el in driver.find_elements(
        "xpath", "//*[@data-odd or @data-tab or @data-value or @data-odds]"
    ):
        attrs = {
            k: el.get_attribute(k)
            for k in ("data-odd", "data-tab", "data-value", "data-odds")
            if el.get_attribute(k)
        }
        print(f"  {describe(el)}  {attrs}")

    print("\n--- Anchor/text nodes containing '1X2' or 'Over/Under' ---")
    for el in driver.find_elements(
        "xpath", "//*[contains(text(),'1X2') or contains(text(),'Over/Under')]"
    ):
        print(f"  {describe(el)}  text={el.text[:60]!r}")

    if args.keep_open:
        input("\nBrowser left open. Press Enter here to close it...")
    driver.quit()


if __name__ == "__main__":
    main()
