"""Price quote: forecast price -> what the farmer gets and what the buyer pays.
G = price_per_kg * qty_kg * quality   (price = admin override if set, else the forecast)
farmer fee % = farmer_fee_pct (default 1%, admin-editable);  farmer payout = G - fee
buyer pays   = G * (1 + buyer_fee%), capped at MRP * qty (buyer never pays above retail)"""

def quote(forecast_kg, qty_kg, quality=1.0, farmer_fee_pct=1.0, buyer_fee_pct=5.0,
          mrp_kg=None, override_kg=None):
    if qty_kg <= 0 or forecast_kg <= 0 or not 0 < quality <= 1.2:
        raise ValueError("qty, price must be > 0 and quality in (0, 1.2]")
    price = override_kg if override_kg else forecast_kg
    g = price * qty_kg * quality
    fee_pct = farmer_fee_pct
    payout = g * (1 - fee_pct / 100)
    buyer = g * (1 + buyer_fee_pct / 100)
    capped = mrp_kg is not None and buyer > mrp_kg * qty_kg
    if capped:
        buyer = mrp_kg * qty_kg
    return {"price_kg": round(price, 2), "gross": round(g, 2), "farmer_fee_pct": fee_pct,
            "farmer_payout": round(payout, 2), "buyer_pays": round(buyer, 2),
            "platform_revenue": round(buyer - payout, 2), "mrp_capped": capped,
            "loss_making": buyer < payout}
