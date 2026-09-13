from betscraper.driver import build_driver
from betscraper.consent import dismiss_overlays
import re

url = "https://www.betexplorer.com/football/england/premier-league/manchester-united-manchester-city/0YOA44w3/"

driver = build_driver(headless=True)
try:
    driver.get(url)
    dismiss_overlays(driver)
    src = driver.page_source
    idx = src.find("match-odds")
    print("First occurrence context:", src[max(0,idx-50):idx+150] if idx != -1 else "NOT FOUND")
    print()
    print("Total occurrences:", src.count("match-odds"))
    # Also check for the 1x2 bestOdds section id
    idx2 = src.find("bestOddsTitle")
    print("bestOddsTitle context:", src[max(0,idx2-100):idx2+300] if idx2 != -1 else "NOT FOUND")
finally:
    driver.quit()
