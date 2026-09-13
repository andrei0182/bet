from betscraper.driver import build_driver
from betscraper.consent import dismiss_overlays

url = "https://www.betexplorer.com/football/usa/mls/fc-dallas-portland-timbers/xG4QJkVA/"
ts_token = "bgQzSI5N"

driver = build_driver(headless=True)
try:
    driver.get(url)
    dismiss_overlays(driver)

    ou_url = f"https://www.betexplorer.com/football/usa/mls/standings/?table=over_under&table_sub=overall&ts={ts_token}&dcheck=0&as-ajax=1&l=en&event_context=xG4QJkVA"

    script = """
    var callback = arguments[arguments.length - 1];
    fetch(arguments[0], {headers: {'X-Requested-With': 'XMLHttpRequest'}, credentials: 'same-origin'})
        .then(function(r) { return r.text(); })
        .then(function(data) { callback(data); })
        .catch(function(err) { callback('ERROR: ' + String(err)); });
    """
    driver.set_script_timeout(15)
    result = driver.execute_async_script(script, ou_url)

    with open("ou_response.html", "w", encoding="utf-8") as f:
        f.write(result)
    print("Saved ou_response.html, length:", len(result))
    print(result[:500])
finally:
    driver.quit()
