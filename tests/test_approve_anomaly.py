"""Test: approve endpoint returns anomaly check result."""
import os, datetime
os.environ.setdefault("KS_PRICES", os.path.join(os.path.dirname(__file__), "..", "data", "prices.csv"))
_FUTURE = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()

from fastapi.testclient import TestClient
from app.main import app
from app.db import conn
from app import escrow

# app.main._load_rates() may override escrow.FEE from the settings table;
# reset to the canonical defaults so other tests see the correct values.
escrow.FEE = float(os.getenv("KS_FARMER_COMMISSION", "0.01"))
escrow.BUYER_MARKUP = float(os.getenv("KS_BUYER_MARKUP", "0.05"))

client = TestClient(app)

def test_approve_returns_anomaly_field():
    # create farmer
    u = client.post("/users", json={"name": "Test Farmer", "role": "farmer", "loc": "Bangalore", "phone": "9876543210"})
    fid = u.json()["id"]
    # create ticket
    t = client.post("/tickets", json={
        "farmer_id": fid, "crop": "Tomato", "qty": 200, "location": "Bangalore",
        "phone": "9876543210", "pref_date": _FUTURE, "pref_slot": "Morning (8-11 am)"
    })
    assert t.status_code == 200, t.text
    tid = t.json()["id"]
    # skip media requirement and set to OPEN directly for testing
    with conn() as c:
        c.execute("UPDATE tickets SET status='OPEN' WHERE id=?", (tid,))
    # approve
    r = client.post(f"/tickets/{tid}/approve", json={
        "grade": "A", "qty": 200, "price": 30.0, "agreed": True
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert "anomaly" in body, f"missing anomaly key: {list(body.keys())}"
    anom = body["anomaly"]
    assert "flag" in anom
    assert "reason" in anom
    assert isinstance(anom["flag"], bool)
