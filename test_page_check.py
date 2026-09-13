from betscraper.driver import build_driver
from betscraper.consent import dismiss_overlays

url = "https://www.betexplorer.com/football/italy/serie-c-group-a/lumezzane-renate/WOsMnh8C/"

driver = build_driver(headless=True)
try:
    driver.get(url)
    dismiss_overlays(driver)
    print("Title:", driver.title)
    print("URL after load:", driver.current_url)
    print("Page source length:", len(driver.page_source))
    with open("page_check.html", "w", encoding="utf-8") as f:
        f.write(driver.page_source)
finally:
    driver.quit()
