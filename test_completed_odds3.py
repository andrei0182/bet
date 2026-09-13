from selenium.webdriver.common.by import By
from betscraper.driver import build_driver
from betscraper.consent import dismiss_overlays

url = "https://www.betexplorer.com/football/albania/abissnet-superiore/partizani-dinamo-city/rNwMOsrJ/"

driver = build_driver(headless=True)
try:
    driver.get(url)
    dismiss_overlays(driver)
    els = driver.find_elements(By.CSS_SELECTOR, "div.table-main__odds, td.table-main__odds")
    print("Odds-related elements found on match page:", len(els))
    titles = driver.find_elements(By.CSS_SELECTOR, "h2#bestOddsTitle")
    for t in titles:
        print("Section title:", t.text)
    body_text = driver.find_element(By.TAG_NAME, "body").text
    print("Contains '1X2':", "1X2" in body_text)
finally:
    driver.quit()
