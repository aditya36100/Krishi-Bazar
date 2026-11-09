"""Tests for quote() wiring into the price endpoint logic."""
from app import pricing, pricing_rules, escrow
import os, math

CSV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "prices.csv")

def test_quote_from_forecast():
    """Simulate what /price/Tomato?qty=100&quality=1.0 does."""
    s = pricing.weekly(pricing.load(CSV), "Tomato")
    f = pricing.forecast(s, 1)
    q = pricing_rules.quote(
        f["point"], 100, 1.0,
        farmer_fee_pct=escrow.FEE * 100,
        buyer_fee_pct=escrow.BUYER_MARKUP * 100,
    )
    assert q["gross"] > 0
    assert q["farmer_payout"] <= q["gross"]
    assert q["buyer_pays"] >= q["gross"]
    assert not q["loss_making"]

def test_quote_with_quality():
    s = pricing.weekly(pricing.load(CSV), "Tomato")
    f = pricing.forecast(s, 1)
    q_full = pricing_rules.quote(f["point"], 100, 1.0,
        farmer_fee_pct=escrow.FEE * 100, buyer_fee_pct=escrow.BUYER_MARKUP * 100)
    q_low = pricing_rules.quote(f["point"], 100, 0.8,
        farmer_fee_pct=escrow.FEE * 100, buyer_fee_pct=escrow.BUYER_MARKUP * 100)
    assert q_low["gross"] < q_full["gross"]
