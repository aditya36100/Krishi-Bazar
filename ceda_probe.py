"""Read-only probe of the CEDA API. Does it have prices after 30 Oct 2025, and is there an arrivals endpoint?
Writes nothing, never prints your key. Run from the repo root:  python ceda_probe.py"""
import datetime, json, ssl, sys, time, urllib.error, urllib.request
import certifi

CTX = ssl.create_default_context(cafile=certifi.where())
BASE = "https://api.ceda.ashoka.edu.in/v1"


def key():
    for line in open(".env"):
        if line.startswith("CEDA_API_KEY="):
            return line.split("=", 1)[1].strip().strip("\"'")
    sys.exit("CEDA_API_KEY not found in .env")


def rows(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            r = rows(v)
            if r:
                return r
    return []


def post(path, body):
    h = {"Authorization": "Bearer " + key(), "Accept": "application/json", "Content-Type": "application/json", "User-Agent": "ks2-research/1.0"}
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120, context=CTX) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:150].decode("utf-8", "replace")
    except Exception as e:
        return None, type(e).__name__


body = {"commodity_id": 78, "state_id": 29, "district_id": [], "market_id": [],
        "from_date": "2025-10-01", "to_date": datetime.date.today().isoformat()}
st, d = post("/agmarknet/prices", body)
r = rows(d) if st == 200 else []
print("prices 2025-10-01 to today -> HTTP", st, "| rows:", len(r), "| last date:", str(r[-1]["date"])[:10] if r else "-")
print("   fields:", sorted(r[0]) if r else d)
for path in ("/agmarknet/quantity", "/agmarknet/arrivals", "/agmarknet/quantities"):  # guessed names
    time.sleep(2)
    st, d = post(path, body)
    r = rows(d) if st == 200 else []
    print(path, "-> HTTP", st, "| rows:", len(r), "| fields:", sorted(r[0]) if r else (d if st != 200 else "-"))