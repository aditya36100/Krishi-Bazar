"""Tests for roadmap item 1: quote() in /orders math, spoilage in /listings, cases endpoints."""
import sqlite3
from app import cases, escrow, pricing_rules


# --- quote in orders: verify 1%/5% math ---

def test_order_amounts_use_1pct_farmer_fee():
    """amount (farmer_payout) = gross * 0.99; buyer_amount = gross * 1.05."""
    price_kg, qty = 50.0, 100.0
    q = pricing_rules.quote(
        price_kg, qty, 1.0,
        farmer_fee_pct=escrow.FEE * 100,
        buyer_fee_pct=escrow.BUYER_MARKUP * 100,
    )
    gross = price_kg * qty  # 5000
    assert q["gross"] == 5000.0
    assert abs(q["farmer_payout"] - gross * (1 - escrow.FEE)) < 0.01
    assert abs(q["buyer_pays"] - gross * (1 + escrow.BUYER_MARKUP)) < 0.01


def test_escrow_fee_is_1pct():
    """escrow.FEE default must be 0.01 (1%), BUYER_MARKUP must be 0.05 (5%)."""
    assert escrow.FEE == 0.01
    assert escrow.BUYER_MARKUP == 0.05


# --- cases wiring: submit -> resolve -> auto ---

def _fresh_cases_db():
    c = sqlite3.connect(":memory:")
    cases.init(c)
    return c


def test_dispute_case_escalates_then_auto():
    c = _fresh_cases_db()
    r1 = cases.submit(c, "Buyer received wrong quantity of Onion")
    assert r1["status"] == "ESCALATE"
    cases.resolve(c, r1["case_id"], "Issue partial refund equal to the shortfall")
    r2 = cases.submit(c, "buyer received wrong onion quantity")
    assert r2["status"] == "AUTO"
    assert "refund" in r2["resolution"].lower()


def test_dispute_case_wrong_stops_auto():
    c = _fresh_cases_db()
    r1 = cases.submit(c, "Tomato delivered was rotten")
    cases.resolve(c, r1["case_id"], "Full refund")
    a = cases.submit(c, "tomato was rotten on delivery")
    assert a["status"] == "AUTO"
    cases.mark_wrong(c, a["matched_case"])
    r3 = cases.submit(c, "tomato was rotten on delivery")
    assert r3["status"] == "ESCALATE"
