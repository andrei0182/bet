from betscraper.driver import build_driver
from betscraper.consent import dismiss_overlays

url = "https://www.betexplorer.com/football/england/premier-league/standings/"

driver = build_driver(headless=True)
try:
    driver.get(url)
    dismiss_overlays(driver)
    print("Final URL:", driver.current_url)
    print("Title:", repr(driver.title))
    print("Page length:", len(driver.page_source))
    with open("standalone_check.html", "w", encoding="utf-8") as f:
        f.write(driver.page_source)
finally:
    driver.quit()
