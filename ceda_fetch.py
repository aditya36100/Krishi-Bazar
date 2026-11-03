"""Download Karnataka daily modal prices from the CEDA API (resumable) and build data/prices.csv (Rs/kg)."""
import datetime, json, os, ssl, sys, time, urllib.error, urllib.request
import certifi
import pandas as pd

CTX = ssl.create_default_context(cafile=certifi.where())
BASE = os.getenv("CEDA_BASE", "https://api.ceda.ashoka.edu.in/v1")
STATE = 29  # Karnataka
START = int(os.getenv("CEDA_START", "2018"))
PAUSE = float(os.getenv("CEDA_PAUSE", "1.5"))
CROPS = {"Potato": 24, "Sweet Potato": 152, "Tomato": 78, "Onion": 23, "Dragon Fruit": 495, "Banana": 19,
         "Mango": 20, "Papaya": 72, "Pomegranate": 190, "Grapes": 22, "Guava": 185, "Capsicum": 164,
         "Cabbage": 154, "Cauliflower": 34, "Carrot": 153, "Beetroot": 157}
CACHE = os.path.join("data", "raw", "cache")
os.makedirs(CACHE, exist_ok=True)


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


def post(body):
    h = {"Authorization": "Bearer " + key(), "Accept": "application/json", "Content-Type": "application/json",
         "User-Agent": "ks2-research/1.0"}
    req = urllib.request.Request(BASE + "/agmarknet/prices", data=json.dumps(body).encode(), headers=h, method="POST")
    for attempt in range(1, 5):
        try:
            with urllib.request.urlopen(req, timeout=180, context=CTX) as r:
                return rows(json.load(r))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 4:
                print("   429 rate limit, waiting %ds" % (20 * attempt)); time.sleep(20 * attempt); continue
            print("   HTTP %s: %r" % (e.code, e.read()[:200])); return None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < 4:
                print("   network problem (%s), retry in %ds" % (type(e).__name__, 15 * attempt)); time.sleep(15 * attempt); continue
            print("   gave up:", type(e).__name__); return None


today = datetime.date.today()
failed = 0
for name, cid in CROPS.items():
    for y in range(START, today.year + 1):
        f = os.path.join(CACHE, "%d_%d.json" % (cid, y))
        if os.path.exists(f):
            continue
        end = "%d-12-31" % y if y < today.year else today.isoformat()
        print("%s %d ..." % (name, y), flush=True)
        r = post({"commodity_id": cid, "state_id": STATE, "district_id": [], "market_id": [],
                  "from_date": "%d-01-01" % y, "to_date": end})
        if r is None:
            failed += 1
            continue
        json.dump(r, open(f, "w"))
        print("   %d rows" % len(r))
        time.sleep(PAUSE)

recs = []
for name, cid in CROPS.items():
    for y in range(START, today.year + 1):
        f = os.path.join(CACHE, "%d_%d.json" % (cid, y))
        if os.path.exists(f):
            for x in json.load(open(f)):
                recs.append({"date": str(x["date"])[:10], "commodity": name, "commodity_id": cid, "state_id": STATE,
                             "min_price": x.get("min_price"), "max_price": x.get("max_price"),
                             "modal_price": x.get("modal_price")})
if not recs:
    sys.exit("no data downloaded; see messages above")
d = pd.DataFrame(recs).drop_duplicates(["commodity", "date"])
d["date"] = pd.to_datetime(d["date"])
d = d.dropna(subset=["modal_price"]).sort_values(["commodity", "date"])
d = d[d["modal_price"] > 0]
os.makedirs(os.path.join("data", "raw"), exist_ok=True)
snap = os.path.join("data", "raw", "ceda_karnataka_%s.csv" % today.strftime("%Y%m%d"))
d.to_csv(snap, index=False)
out = pd.DataFrame({"date": d["date"], "commodity": d["commodity"], "modal_price": d["modal_price"] / 100.0})
out.to_csv(os.path.join("data", "prices.csv"), index=False)
if os.path.exists(os.path.join("data", "SYNTHETIC")):
    os.remove(os.path.join("data", "SYNTHETIC"))
print("\nsnapshot:", snap)
print("%-14s %7s %11s %11s %7s" % ("crop", "rows", "from", "to", "weeks"))
for name, g in d.groupby("commodity"):
    wk = g.set_index("date")["modal_price"].resample("W").mean().dropna()
    print("%-14s %7d %11s %11s %7d" % (name, len(g), g["date"].min().date(), g["date"].max().date(), len(wk)))
print("\nwrote data/prices.csv in Rs/kg (CEDA gives Rs/quintal, divided by 100). failed chunks:", failed)
print("Check: Tomato median Rs/kg =", round(float(out[out.commodity == "Tomato"].modal_price.median()), 1) if (out.commodity == "Tomato").any() else "n/a")
