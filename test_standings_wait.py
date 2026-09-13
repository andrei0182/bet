from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from betscraper.driver import build_driver
from betscraper.consent import dismiss_overlays

url = "https://www.betexplorer.com/football/usa/mls/fc-dallas-portland-timbers/xG4QJkVA/"

driver = build_driver(headless=True)
try:
    driver.get(url)
    dismiss_overlays(driver)

    # Try waiting for it directly first
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div#standingsComponent"))
        )
        print("Found #standingsComponent WITHOUT scrolling.")
    except TimeoutException:
        print("Not found within 10s — scrolling down to trigger lazy-load...")
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div#standingsComponent"))
            )
            print("Found #standingsComponent AFTER scrolling.")
        except TimeoutException:
            print("Still not found after scrolling + 15s wait.")

    els = driver.find_elements(By.CSS_SELECTOR, "div#standingsComponent")
    if els:
        html = els[0].get_attribute("outerHTML")
        print("Length of standingsComponent HTML:", len(html))
        with open("standings_component.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("Saved to standings_component.html")
finally:
    driver.quit()
