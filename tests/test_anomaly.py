import os, pandas as pd
from app.anomaly import PriceChecker, BaselineChecker, daily

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


def test_baseline_normal_price_ok_and_extremes_flagged():
    bc = BaselineChecker(D)
    med = float(daily(D, "Tomato").values[-28:].mean())
    assert bc.check("Tomato", med)["flag"] is False
    assert bc.check("Tomato", med * 5)["flag"] is True
    assert bc.check("Tomato", med * 0.1)["flag"] is True

def test_baseline_unknown_crop():
    r = BaselineChecker(D).check("Dragonfruit", 50)
    assert r["flag"] is False and r["level"] == "UNKNOWN"

def test_baseline_returns_reason_and_median():
    bc = BaselineChecker(D)
    r = bc.check("Onion", 500.0)
    assert "reason" in r and "recent_median" in r
    assert isinstance(r["recent_median"], float)
