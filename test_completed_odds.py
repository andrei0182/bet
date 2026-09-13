from selenium.webdriver.common.by import By
from betscraper.driver import build_driver
from betscraper.consent import dismiss_overlays
from betscraper import selectors as sel

driver = build_driver(headless=True)
try:
    driver.get("https://www.betexplorer.com/football/results/?year=2026&month=09&day=13")
    dismiss_overlays(driver)

    rows = driver.find_elements(By.CSS_SELECTOR, sel.MATCH_ROW)
    for row in rows:
        score_cells = row.find_elements(By.CSS_SELECTOR, sel.SCORE_CELL)
        if score_cells and score_cells[0].text.strip():
            odds_cells = row.find_elements(By.CSS_SELECTOR, sel.ODDS_CELLS)
            print("Score:", score_cells[0].text.strip())
            print("Number of odds cells found on this completed row:", len(odds_cells))
            for c in odds_cells:
                print("  odds cell text:", repr(c.text))
            print("Row outerHTML snippet:", row.get_attribute("outerHTML")[:800])
            break
finally:
    driver.quit()
