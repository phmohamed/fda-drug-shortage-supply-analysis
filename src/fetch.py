"""Download all FDA drug shortage records from openFDA (100 per page)."""
import json, urllib.request, time
rows, skip = [], 0
while True:
    url = f"https://api.fda.gov/drug/shortages.json?limit=100&skip={skip}"
    for i in range(3):
        try:
            d = json.load(urllib.request.urlopen(url, timeout=60)); break
        except Exception:
            time.sleep(3)
    else:
        raise SystemExit("fetch failed")
    rows += d["results"]
    if len(d["results"]) < 100: break
    skip += 100
json.dump(rows, open("data/shortages_raw.json", "w"))
print(len(rows), "records", d["meta"].get("last_updated"))
