from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import time

options = Options()
options.add_argument("--headless=new")
options.add_argument("--window-size=1920,1080")
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")

service = Service(log_output="chromedriver.log", service_args=["--verbose"])
driver = webdriver.Chrome(service=service, options=options)
driver.get("https://www.betexplorer.com/football/results/?year=2026&month=09&day=13")
time.sleep(15)
with open("debug_page2.html", "w", encoding="utf-8") as f:
    f.write(driver.page_source)
print("Still alive —", len(driver.page_source), "chars")
driver.quit()
