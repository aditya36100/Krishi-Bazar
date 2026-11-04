import pytest
from app.pricing_rules import quote

def test_apple_example():
    q = quote(47.1, 100, farmer_fee_pct=5, mrp_kg=50)
    assert q["gross"] == 4710 and q["buyer_pays"] == 4945.5 and not q["mrp_capped"]
    assert q["farmer_payout"] == 4474.5 and q["platform_revenue"] == 471.0

def test_mrp_cap():
    q = quote(49, 100, mrp_kg=50); assert q["buyer_pays"] == 5000 and q["mrp_capped"]

def test_admin_override_and_quality():
    q = quote(40, 10, quality=0.9, override_kg=50); assert q["gross"] == 450

def test_bad_input():
    with pytest.raises(ValueError): quote(10, 0)

def test_defaults():
    q = quote(47.1, 100)
    assert q['farmer_payout'] == 4662.9 and q['buyer_pays'] == 4945.5 and q['platform_revenue'] == 282.6
