diff --git a/app/db.py b/app/db.py
index c6a6205..50d5dfb 100644
--- a/app/db.py
+++ b/app/db.py
@@ -43,7 +43,8 @@ def init():
         except sqlite3.OperationalError:
             pass
         for ddl in ("ALTER TABLE listings ADD COLUMN variety TEXT DEFAULT ''",
-                    "ALTER TABLE orders ADD COLUMN buyer_amount REAL"):
+                    "ALTER TABLE orders ADD COLUMN buyer_amount REAL",
+                    "ALTER TABLE orders ADD COLUMN gross REAL"):
             try:
                 c.execute(ddl)
             except sqlite3.OperationalError:
diff --git a/app/escrow.py b/app/escrow.py
index 0f78071..1a52f70 100644
--- a/app/escrow.py
+++ b/app/escrow.py
@@ -23,10 +23,22 @@ def _log(c, oid, event, detail):
     c.execute("INSERT INTO ledger(order_id,event,detail,ts,prev_hash,hash) VALUES(?,?,?,?,?,?)",
               (oid, event, d, ts, prev, h))
 
+def start_tx(c, oid):
+    """Log PLACED on an already-open transaction, so the order row and its ledger entry commit together."""
+    o = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
+    _log(c, oid, "PLACED", {"amount": o["amount"], "deposit_pct": o["deposit_pct"]})
+
 def start(oid):
     with tx() as c:
-        o = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
-        _log(c, oid, "PLACED", {"amount": o["amount"], "deposit_pct": o["deposit_pct"]})
+        start_tx(c, oid)
+
+def settlement(o):
+    """(farmer_gets, commission) for an order row (sqlite3.Row or dict).
+    New orders store gross = price*qty*quality and amount = the farmer's NET payout, both fixed at order time.
+    Legacy rows (gross is NULL) stored the gross value in amount, so the fee is applied here, as before."""
+    if "gross" in o.keys() and o["gross"] is not None:
+        return round(o["amount"], 2), round(o["gross"] - o["amount"], 2)
+    return round(o["amount"] * (1 - FEE), 2), round(o["amount"] * FEE, 2)
 
 def move(oid, new, detail=None):
     with tx() as c:
@@ -39,8 +51,11 @@ def move(oid, new, detail=None):
         d = dict(detail or {}, amount=o["amount"])
         if new == "RELEASED":
             bp = o["buyer_amount"] or round(o["amount"] * (1 + BUYER_MARKUP), 2)
-            d.update(commission=round(o["amount"] * FEE, 2), farmer_gets=round(o["amount"] * (1 - FEE), 2),
-                     buyer_paid=bp, platform_total=round(bp - o["amount"] * (1 - FEE), 2))
+            farmer_gets, commission = settlement(o)
+            d.update(commission=commission, farmer_gets=farmer_gets,
+                     buyer_paid=bp, platform_total=round(bp - farmer_gets, 2))
+        if new in ("REFUNDED", "CANCELLED"):  # stock goes back in the same transaction as the state change
+            c.execute("UPDATE listings SET qty=qty+? WHERE id=?", (o["qty"], o["listing_id"]))
         _log(c, oid, new, d)
 
 def verify_chain():
@@ -106,5 +121,6 @@ def buyer_cancel(oid):
         charge = _cancel_charge(o, age)
         new = "CANCELLED" if o["state"] == "PLACED" else "REFUNDED"
         c.execute("UPDATE orders SET state=? WHERE id=?", (new, oid))
+        c.execute("UPDATE listings SET qty=qty+? WHERE id=?", (o["qty"], o["listing_id"]))
         _log(c, oid, new, {"reason": "buyer cancelled" + ("" if age <= CANCEL_MINUTES else " after the free window"), "amount": o["amount"], "cancel_charge": charge})
         return charge
diff --git a/app/main.py b/app/main.py
index e3ba220..a1be5fb 100644
--- a/app/main.py
+++ b/app/main.py
@@ -4,7 +4,7 @@ from fastapi.responses import FileResponse
 from fastapi.middleware.cors import CORSMiddleware
 from pydantic import BaseModel
 from . import db, escrow, pricing, pricing_rules, reliability, spoilage, cases, anomaly
-from .db import conn
+from .db import conn, tx
 from . import idempotency, imagecheck, ratelimit
 
 db.init()
@@ -124,21 +124,26 @@ def place(o: Order, idempotency_key: str = Header(default="")):
     return resp
 
 def _place(o: Order):
+    # Reads that do not depend on stock happen first, outside the write lock.
+    subbed = _sub(o.buyer_id)["active"]
+    buyer_min = _buyer_min(o.buyer_id)
     with conn() as c:
+        buyer = c.execute("SELECT loc FROM users WHERE id=?", (o.buyer_id,)).fetchone()
+    buyer_loc = (buyer["loc"] if buyer else "") or ""
+    # One BEGIN IMMEDIATE transaction: stock check, stock decrement, order row and PLACED ledger entry
+    # commit (or roll back) together, so two buyers can never take the same lot.
+    with tx() as c:
         l = c.execute("SELECT * FROM listings WHERE id=?", (o.listing_id,)).fetchone()
         if not l:
             raise HTTPException(404, "listing not found")
         o.qty = l["qty"]  # whole lot only: buyers cannot choose a quantity
         if o.qty <= 0:
             raise HTTPException(400, "This lot is no longer available")
-        subbed = _sub(o.buyer_id)["active"]
         if not subbed and _opens_at(l) > datetime.datetime.now():
             raise HTTPException(403, "Early-access window: opens to all buyers at " + _opens_at(l).strftime("%d %b %H:%M"))
-        mn = min(_buyer_min(o.buyer_id), l["qty"])
+        mn = min(buyer_min, l["qty"])
         if o.qty < mn:
             raise HTTPException(400, f"Minimum order is {mn:g} kg for your buyer type")
-        buyer = c.execute("SELECT loc FROM users WHERE id=?", (o.buyer_id,)).fetchone()
-        buyer_loc = (buyer["loc"] if buyer else "") or ""
         age_h = spoilage.hours_since(l["harvest_date"]) if l["harvest_date"] else 0
         sp = spoilage.assess(l["crop"], age_h, l["loc"] or "", buyer_loc)
         _q = pricing_rules.quote(
@@ -146,16 +151,35 @@ def _place(o: Order):
             farmer_fee_pct=escrow.FEE * 100,
             buyer_fee_pct=escrow.BUYER_MARKUP * 100,
         )
-        oid = c.execute("INSERT INTO orders(listing_id,buyer_id,qty,amount,buyer_amount,deposit_pct,created) VALUES(?,?,?,?,?,?,?)",
-                        (o.listing_id, o.buyer_id, o.qty, _q["farmer_payout"], _q["buyer_pays"], o.deposit_pct,
+        cur = c.execute("UPDATE listings SET qty=qty-? WHERE id=? AND qty>=?", (o.qty, o.listing_id, o.qty))
+        if cur.rowcount != 1:
+            raise HTTPException(409, "This lot was just taken by another buyer")
+        # amount = farmer NET payout, gross = price*qty*quality, buyer_amount = what the buyer pays (all fixed now)
+        oid = c.execute("INSERT INTO orders(listing_id,buyer_id,qty,amount,gross,buyer_amount,deposit_pct,created) VALUES(?,?,?,?,?,?,?,?)",
+                        (o.listing_id, o.buyer_id, o.qty, _q["farmer_payout"], _q["gross"], _q["buyer_pays"], o.deposit_pct,
                          datetime.datetime.now().isoformat())).lastrowid
-        c.execute("UPDATE listings SET qty=qty-? WHERE id=?", (o.qty, o.listing_id))
-    escrow.start(oid)
+        escrow.start_tx(c, oid)
     resp = {"id": oid, "state": "PLACED"}
     if sp.get("warn"):
         resp["spoilage"] = sp
     return resp
 
+class DisputeIn(BaseModel):
+    text: str
+
+# NOTE: must be registered BEFORE the generic /orders/{oid}/{action} route below, or that route swallows it (404 "unknown action").
+@app.post("/orders/{oid}/dispute_case")
+def dispute_case(oid: int, d: DisputeIn):
+    """Submit a dispute description to the case memory; may auto-resolve or escalate to admin."""
+    if not d.text.strip():
+        raise HTTPException(400, "dispute text is required")
+    with conn() as c:
+        if not c.execute("SELECT 1 FROM orders WHERE id=?", (oid,)).fetchone():
+            raise HTTPException(404, "order not found")
+        result = cases.submit(c, d.text.strip())
+    result["order_id"] = oid
+    return result
+
 @app.post("/orders/{oid}/{action}")
 def act(oid: int, action: str):
     if action == "undo":
@@ -169,10 +193,7 @@ def act(oid: int, action: str):
             escrow.buyer_cancel(oid)
         except ValueError as e:
             raise HTTPException(400, str(e))
-        with conn() as c:
-            o = c.execute("SELECT qty, listing_id FROM orders WHERE id=?", (oid,)).fetchone()
-            c.execute("UPDATE listings SET qty=qty+? WHERE id=?", (o["qty"], o["listing_id"]))
-        return {"id": oid, "state": "cancelled"}
+        return {"id": oid, "state": "cancelled"}  # stock was restored inside escrow.buyer_cancel's transaction
     if action not in ACTIONS:
         raise HTTPException(404, "unknown action")
     new = ACTIONS[action]
@@ -182,8 +203,6 @@ def act(oid: int, action: str):
         raise HTTPException(400, str(e))
     with conn() as c:
         o = c.execute("SELECT o.*, l.farmer_id FROM orders o JOIN listings l ON l.id=o.listing_id WHERE o.id=?", (oid,)).fetchone()
-        if new in ("REFUNDED", "CANCELLED"):
-            c.execute("UPDATE listings SET qty=qty+? WHERE id=?", (o["qty"], o["listing_id"]))
         if new == "RELEASED":
             for pid, kind in ((o["farmer_id"], "farmer_fulfil"), (o["buyer_id"], "buyer_accept")):
                 c.execute("INSERT INTO outcomes(order_id,party_id,kind,ok) VALUES(?,?,?,1)", (oid, pid, kind))
@@ -195,19 +214,6 @@ def fault(oid: int, party_id: int):  # admin marks the party at fault after a di
         c.execute("INSERT INTO outcomes(order_id,party_id,kind,ok) VALUES(?,?,?,0)", (oid, party_id, "fault"))
     return {"ok": True}
 
-class DisputeIn(BaseModel):
-    text: str
-
-@app.post("/orders/{oid}/dispute_case")
-def dispute_case(oid: int, d: DisputeIn):
-    """Submit a dispute description to the case memory; may auto-resolve or escalate to admin."""
-    if not d.text.strip():
-        raise HTTPException(400, "dispute text is required")
-    with conn() as c:
-        result = cases.submit(c, d.text.strip())
-    result["order_id"] = oid
-    return result
-
 @app.get("/cases")
 def list_cases():
     """Admin: list all cases."""
@@ -272,13 +278,17 @@ def rel(user_id: int):
 def summary():
     with conn() as c:
         g = lambda q: c.execute(q).fetchone()[0]
-        gmv = g("SELECT COALESCE(SUM(amount),0) FROM orders WHERE state='RELEASED'")
+        gmv = fee = bp = 0.0  # per released order: gross value, platform commission, what buyers paid
+        for r in c.execute("SELECT amount, gross, buyer_amount FROM orders WHERE state='RELEASED'").fetchall():
+            farmer_gets, commission = escrow.settlement(r)
+            gross = farmer_gets + commission
+            gmv += gross; fee += commission
+            bp += r["buyer_amount"] or round(gross * (1 + escrow.BUYER_MARKUP), 2)
         prem = g("SELECT AVG(l.price/l.mandi_ref-1)*100 FROM orders o JOIN listings l ON l.id=o.listing_id "
                  "WHERE o.state='RELEASED' AND l.mandi_ref>0")
-        bp = g(f"SELECT COALESCE(SUM(COALESCE(buyer_amount, amount*{1 + escrow.BUYER_MARKUP})),0) FROM orders WHERE state='RELEASED'")
         subs = g("SELECT COALESCE(SUM(price),0) FROM subscriptions")
         out = {"users": g("SELECT COUNT(*) FROM users"), "orders": g("SELECT COUNT(*) FROM orders"),
-               "gmv_released": gmv, "platform_fee": round(gmv * escrow.FEE, 2), "buyer_margin": round(bp - gmv, 2), "subscription_revenue": subs,
+               "gmv_released": round(gmv, 2), "platform_fee": round(fee, 2), "buyer_margin": round(bp - gmv, 2), "subscription_revenue": subs,
                "avg_farmer_premium_pct": None if prem is None else round(prem, 1)}
     out["ledger_intact"] = escrow.verify_chain()[0]
     return out
@@ -328,11 +338,11 @@ def orders(view: str = "admin"):
     for d in rows:
         bp = d.get("buyer_amount") or round(d["amount"] * (1 + escrow.BUYER_MARKUP), 2)
         if view == "buyer":
-            d["amount"] = bp; d.pop("buyer_amount", None); d.pop("price", None)
+            d["amount"] = bp; d.pop("buyer_amount", None); d.pop("price", None); d.pop("gross", None)  # buyers never see the farmer-side price
             if d["state"] in ("PLACED", "FUNDED"):
                 d["cancel_charge"] = escrow.cancel_preview(d["id"])
         elif view == "farmer":
-            d["payout"] = round(d["amount"] * (1 - escrow.FEE), 2); d.pop("buyer_amount", None)
+            d["payout"] = escrow.settlement(d)[0]; d.pop("buyer_amount", None)
         else:
             d["buyer_amount"] = bp
     return rows
diff --git a/requirements.txt b/requirements.txt
index 13f6c5b..9f83573 100644
--- a/requirements.txt
+++ b/requirements.txt
@@ -1,6 +1,13 @@
-fastapi
-uvicorn
-numpy
-pandas
-pillow
-scipy
+# Versions taken from the project's own .venv (Python 3.12). Pinned exactly where CONTEXT.md names a version.
+fastapi>=0.142
+uvicorn>=0.54
+numpy>=2.5
+pandas>=3.0
+pillow>=13.0
+scipy>=1.18
+scikit-learn==1.9.1
+statsmodels==0.15.0
+lightgbm==4.7.0
+certifi>=2026.1
+pytest>=9.2
+httpx2>=2.16
diff --git a/tests/conftest.py b/tests/conftest.py
new file mode 100644
index 0000000..c14eac4
--- /dev/null
+++ b/tests/conftest.py
@@ -0,0 +1,28 @@
+"""Test isolation: no test may touch krishi.db.
+
+app.main runs db.init() at import time, so KS_DB must point at a throwaway file BEFORE the first
+`app` import; each test then gets its own fresh database and default fee settings.
+"""
+import os
+import tempfile
+
+_TMP = tempfile.mkdtemp(prefix="ks_tests_")
+os.environ["KS_DB"] = os.path.join(_TMP, "import_time.db")
+
+import pytest  # noqa: E402
+from app import cases, db, escrow, idempotency, imagecheck  # noqa: E402
+
+
+@pytest.fixture(autouse=True)
+def _isolated_db(tmp_path, monkeypatch):
+    monkeypatch.setattr(db, "DB", str(tmp_path / "test.db"))
+    db.init()
+    with db.conn() as c:
+        cases.init(c)
+        idempotency.init(c)
+        imagecheck.init(c)
+    # app.main._load_rates() and admin-settings tests mutate these globals; always start from the canonical defaults
+    monkeypatch.setattr(escrow, "FEE", 0.01)
+    monkeypatch.setattr(escrow, "BUYER_MARKUP", 0.05)
+    monkeypatch.setattr(escrow, "CANCEL_FEE", 0.10)
+    yield
diff --git a/tests/test_phase_a.py b/tests/test_phase_a.py
new file mode 100644
index 0000000..6aaf14b
--- /dev/null
+++ b/tests/test_phase_a.py
@@ -0,0 +1,161 @@
+"""Phase A regression tests: fee settlement, dispute route, oversell race, stock restore, DB isolation."""
+import json
+import os
+import threading
+
+import pytest
+from fastapi import HTTPException
+from fastapi.testclient import TestClient
+
+from app import db, escrow, pricing_rules, replay
+from app import main
+
+client = TestClient(main.app)
+
+
+def _farmer():
+    with db.conn() as c:
+        return c.execute("INSERT INTO users(name,role,loc) VALUES('F','farmer','Kolar')").lastrowid
+
+
+def _buyer():
+    with db.conn() as c:
+        return c.execute("INSERT INTO users(name,role,loc,buyer_type) VALUES('B','buyer','Bengaluru','Restaurant')").lastrowid
+
+
+def _listing(fid, price=30.0, qty=200.0):
+    with db.conn() as c:
+        return c.execute("INSERT INTO listings(farmer_id,crop,qty,price,loc,variety) "
+                         "VALUES(?,'Tomato',?,?,'Kolar','Hybrid')", (fid, qty, price)).lastrowid
+
+
+def _stock(lid):
+    with db.conn() as c:
+        return c.execute("SELECT qty FROM listings WHERE id=?", (lid,)).fetchone()[0]
+
+
+def _order(lid, bid):
+    r = client.post("/orders", json={"listing_id": lid, "buyer_id": bid, "qty": 1})
+    assert r.status_code == 200, r.text
+    return r.json()["id"]
+
+
+# ---- A2: fee settlement must equal quote() -------------------------------------------------
+
+@pytest.mark.parametrize("price,qty,fee,markup", [
+    (30.0, 200, 0.01, 0.05), (47.1, 100, 0.01, 0.05), (12.34, 333, 0.02, 0.03),
+    (99.99, 150, 0.0, 0.10), (7.5, 1000, 0.05, 0.0)])
+def test_released_ledger_matches_quote(monkeypatch, price, qty, fee, markup):
+    monkeypatch.setattr(escrow, "FEE", fee)
+    monkeypatch.setattr(escrow, "BUYER_MARKUP", markup)
+    oid = _order(_listing(_farmer(), price, qty), _buyer())
+    for a in ("fund", "harvest", "ship", "deliver", "release"):
+        assert client.post(f"/orders/{oid}/{a}").status_code == 200
+    q = pricing_rules.quote(price, qty, 1.0, farmer_fee_pct=fee * 100, buyer_fee_pct=markup * 100)
+    d = json.loads(client.get(f"/orders/{oid}/ledger").json()[-1]["detail"])
+    assert d["farmer_gets"] == pytest.approx(q["farmer_payout"], abs=0.011)
+    assert d["buyer_paid"] == pytest.approx(q["buyer_pays"], abs=0.011)
+    assert d["platform_total"] == pytest.approx(q["platform_revenue"], abs=0.011)
+    assert d["commission"] == pytest.approx(q["gross"] - q["farmer_payout"], abs=0.011)
+    farmer_view = [o for o in client.get("/orders?view=farmer").json() if o["id"] == oid][0]
+    assert farmer_view["payout"] == pytest.approx(q["farmer_payout"], abs=0.011)
+    s = client.get("/admin/summary").json()
+    assert s["gmv_released"] == pytest.approx(q["gross"], abs=0.011)
+    assert s["platform_fee"] + s["buyer_margin"] == pytest.approx(q["platform_revenue"], abs=0.02)
+    assert s["ledger_intact"] is True
+
+
+def test_legacy_gross_rows_keep_old_settlement():
+    """Orders written before the `gross` column stored the gross value in `amount`; fee is applied at release."""
+    with db.conn() as c:
+        oid = c.execute("INSERT INTO orders(listing_id,buyer_id,qty,amount,deposit_pct,created) "
+                        "VALUES(1,1,100,1000,0.3,'x')").lastrowid
+    escrow.start(oid)
+    for s in ("FUNDED", "HARVESTED", "SHIPPED", "DELIVERED", "RELEASED"):
+        escrow.move(oid, s)
+    with db.conn() as c:
+        d = json.loads(c.execute("SELECT detail FROM ledger WHERE order_id=? AND event='RELEASED'", (oid,)).fetchone()[0])
+    assert d["farmer_gets"] == 990.0 and d["commission"] == 10.0
+    assert escrow.verify_chain()[0] is True
+
+
+# ---- A3: dispute route must not be shadowed ---------------------------------------------------
+
+def test_dispute_case_reachable_over_http_and_learns():
+    oid = _order(_listing(_farmer()), _buyer())
+    r1 = client.post(f"/orders/{oid}/dispute_case", json={"text": "Tomatoes arrived rotten after 2 days of delivery"})
+    assert r1.status_code == 200, r1.text
+    assert r1.json()["status"] == "ESCALATE"
+    cid = r1.json()["case_id"]
+    assert client.post(f"/cases/{cid}/resolve", json={"resolution": "Refund 50%"}).status_code == 200
+    r2 = client.post(f"/orders/{oid}/dispute_case", json={"text": "tomato came rotten, delivery took 2 days"})
+    assert r2.status_code == 200 and r2.json()["status"] == "AUTO" and "Refund 50%" in r2.json()["resolution"]
+    assert client.post("/orders/99999/dispute_case", json={"text": "x"}).status_code == 404
+    assert client.post(f"/orders/{oid}/fund").status_code == 200   # the generic action route still works
+
+
+# ---- A4: no overselling under concurrency -----------------------------------------------------
+
+def test_no_oversell_under_concurrent_buyers():
+    fid, buyers = _farmer(), [_buyer() for _ in range(8)]
+    errors = []
+    for _ in range(5):
+        for lid in [_listing(fid) for _ in range(20)]:
+            bar, out = threading.Barrier(8), []
+
+            def go(b, lid=lid, bar=bar, out=out):
+                bar.wait()
+                try:
+                    main._place(main.Order(listing_id=lid, buyer_id=b, qty=1))
+                    out.append("ok")
+                except HTTPException:
+                    out.append("rejected")
+                except Exception as e:  # any other failure is a bug
+                    errors.append(repr(e))
+
+            ts = [threading.Thread(target=go, args=(b,)) for b in buyers]
+            [t.start() for t in ts]
+            [t.join() for t in ts]
+            assert out.count("ok") == 1, f"lot {lid} sold {out.count('ok')} times"
+    assert not errors, errors[:3]
+    with db.conn() as c:
+        assert c.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 100
+        assert c.execute("SELECT COUNT(*) FROM listings WHERE qty<0").fetchone()[0] == 0
+    assert escrow.verify_chain()[0] and replay.check()["ok"]
+
+
+# ---- A4: stock restore is atomic with the state change ------------------------------------------
+
+def test_cancel_and_refund_restore_stock_exactly_once():
+    lid, bid = _listing(_farmer()), _buyer()
+    oid = _order(lid, bid)
+    assert _stock(lid) == 0
+    assert client.post(f"/orders/{oid}/ship").status_code == 400      # illegal move must not change stock
+    assert _stock(lid) == 0
+    assert client.post(f"/orders/{oid}/buyer_cancel").status_code == 200   # PLACED -> CANCELLED
+    assert _stock(lid) == 200
+    assert client.post(f"/orders/{oid}/buyer_cancel").status_code == 400   # second cancel: no double restore
+    assert _stock(lid) == 200
+    oid = _order(lid, bid)
+    client.post(f"/orders/{oid}/fund")
+    assert client.post(f"/orders/{oid}/refund").status_code == 200         # FUNDED -> REFUNDED
+    assert _stock(lid) == 200
+    oid = _order(lid, bid)
+    client.post(f"/orders/{oid}/fund")
+    assert client.post(f"/orders/{oid}/buyer_cancel").status_code == 200   # FUNDED -> REFUNDED via buyer
+    assert _stock(lid) == 200
+    assert replay.check()["ok"] and escrow.verify_chain()[0]
+
+
+def test_order_and_placed_ledger_entry_commit_together():
+    oid = _order(_listing(_farmer()), _buyer())
+    with db.conn() as c:
+        assert c.execute("SELECT COUNT(*) FROM ledger WHERE order_id=? AND event='PLACED'", (oid,)).fetchone()[0] == 1
+    assert replay.check()["orders_without_ledger"] == []
+
+
+# ---- A5: isolation --------------------------------------------------------------------------------
+
+def test_tests_never_touch_krishi_db(tmp_path):
+    assert os.path.basename(db.DB) != "krishi.db"
+    assert db.DB.startswith(str(tmp_path))