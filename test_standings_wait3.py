import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from betscraper.driver import build_driver
from betscraper.consent import dismiss_overlays

url = "https://www.betexplorer.com/football/usa/mls/fc-dallas-portland-timbers/xG4QJkVA/"

driver = build_driver(headless=True)
try:
    t0 = time.time()
    driver.get(url)
    dismiss_overlays(driver)
    print(f"After get+dismiss: {time.time()-t0:.1f}s")

    try:
        WebDriverWait(driver, 60).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div#standingsComponent"))
        )
        print(f"FOUND #standingsComponent after {time.time()-t0:.1f}s total.")
        els = driver.find_elements(By.CSS_SELECTOR, "div#standingsComponent")
        html = els[0].get_attribute("outerHTML")
        with open("standings_component.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("Saved standings_component.html, length:", len(html))
    except TimeoutException:
        print(f"STILL not found after {time.time()-t0:.1f}s.")
finally:
    driver.quit()
