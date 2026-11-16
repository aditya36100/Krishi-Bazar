import os, pandas as pd
from app.anomaly import PriceChecker, daily

CSV = os.path.join(os.path.dirname(__file__), "..", "data", "prices.csv")
D = pd.read_csv(CSV, parse_dates=["date"])

def test_normal_price_ok_and_extremes_flagged():
    pc = PriceChecker(D)
    med = float(daily(D, "Tomato").values[-28:].mean())
    assert pc.check("Tomato", med)["flag"] is False
    assert pc.check("Tomato", med * 4)["flag"] is True
    assert pc.check("Tomato", med * 0.2)["flag"] is True

def test_unknown_crop_not_flagged():
    r = PriceChecker(D).check("Dragonfruit", 50)
    assert r["flag"] is False and r["level"] == "UNKNOWN"
