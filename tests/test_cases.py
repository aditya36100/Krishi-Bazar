import sqlite3
from app import cases

def db():
    c = sqlite3.connect(":memory:"); cases.init(c); return c

def test_learns_from_manual_solution():
    c = db()
    r = cases.submit(c, "Tomatoes arrived rotten after 2 days of delivery")
    assert r["status"] == "ESCALATE"
    cases.resolve(c, r["case_id"], "Refund 50% and flag the seller's delivery time")
    r2 = cases.submit(c, "tomato came rotten, delivery took 2 days")
    assert r2["status"] == "AUTO" and "Refund 50%" in r2["resolution"]

def test_unrelated_escalates_and_auto_off():
    c = db()
    r = cases.submit(c, "Tomatoes arrived rotten after 2 days of delivery")
    cases.resolve(c, r["case_id"], "Refund 50%", auto_ok=False)
    assert cases.submit(c, "tomato came rotten, delivery took 2 days")["status"] == "ESCALATE"
    assert cases.submit(c, "how do I change my phone number")["status"] == "ESCALATE"

def test_mark_wrong_stops_auto():
    c = db()
    r = cases.submit(c, "Onion quantity was less than ordered")
    cases.resolve(c, r["case_id"], "Refund difference")
    a = cases.submit(c, "onion quantity less than ordered")
    assert a["status"] == "AUTO"
    cases.mark_wrong(c, a["matched_case"])
    assert cases.submit(c, "onion quantity less than ordered")["status"] == "ESCALATE"
