from betscraper.driver import build_driver
from betscraper.consent import dismiss_overlays

# un meci programat, nu finalizat, unde 1X2 chiar se vede pe pagina de listă
url = "https://www.betexplorer.com/football/england/premier-league/manchester-united-manchester-city/0YOA44w3/"

driver = build_driver(headless=True)
try:
    driver.get(url)
    dismiss_overlays(driver)
    src = driver.page_source
    import re
    matches = re.findall(r'match-odds/[A-Za-z0-9]+/\d+/[a-z0-9]+/', src)
    print("Found match-odds URL patterns:", set(matches))
finally:
    driver.quit()
