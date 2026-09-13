import time
from selenium.webdriver.common.by import By
from betscraper.driver import build_driver
from betscraper.consent import dismiss_overlays

url = "https://www.betexplorer.com/football/england/premier-league/standings/"

driver = build_driver(headless=True)
try:
    t0 = time.time()
    driver.get(url)
    dismiss_overlays(driver)
    print(f"[{time.time()-t0:.1f}s] Page loaded, title: {driver.title}")

    tabs = driver.find_elements(By.XPATH, "//a[contains(@class,'standings__submenu-a') and normalize-space(.)='Over/Under']")
    print(f"[{time.time()-t0:.1f}s] O/U tabs found: {len(tabs)}")
    if tabs:
        driver.execute_script("arguments[0].click();", tabs[0])
        print(f"[{time.time()-t0:.1f}s] Clicked O/U tab")
        time.sleep(2)
        table = driver.find_elements(By.CSS_SELECTOR, "table[id='table-type-6-2.5']")
        print(f"[{time.time()-t0:.1f}s] table-type-6-2.5 found: {len(table)}")
        if table:
            rows = table[0].find_elements(By.CSS_SELECTOR, "tbody tr")
            print(f"[{time.time()-t0:.1f}s] rows in table: {len(rows)}")
finally:
    driver.quit()
