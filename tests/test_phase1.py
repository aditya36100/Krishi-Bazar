"""Phase 1 regression tests: double fee, route shadowing, oversell race, cancel stock restore."""
import json, threading, pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from app import main, escrow, pricing_rules
from app.db import conn
from tests.helpers import register, admin

client = TestClient(main.app)


def _mk(price, qty):
    f, fh = register(client, "farmer")
    b, bh = register(client, "buyer")
    with conn() as c:
        lid = c.execute("INSERT INTO listings(farmer_id,crop,qty,price,loc,status) VALUES(?,?,?,?,?,'ACTIVE')",
                        (f, "Tomato", qty, price, "Bangalore")).lastrowid
    return f, b, lid, fh, bh


def _step(oid, action, hdr):
    r = client.post(f"/orders/{oid}/{action}", headers=hdr)
    assert r.status_code == 200, (action, r.text)


def _release(oid, fh, bh):
    _step(oid, "fund", bh); _step(oid, "harvest", fh); _step(oid, "ship", fh)
    _step(oid, "deliver", bh); _step(oid, "release", bh)


def _released_detail(oid):
    led = client.get(f"/orders/{oid}/ledger", headers=admin(client)).json()
    return json.loads([x for x in led if x["event"] == "RELEASED"][0]["detail"])


@pytest.mark.parametrize("price,qty,fee,mk", [(30, 200, 0.01, 0.05), (47.5, 123, 0.02, 0.05),
                                              (12.34, 1000, 0.0, 0.03), (99.99, 57, 0.01, 0.10)])
def test_released_ledger_equals_quote(monkeypatch, price, qty, fee, mk):
    monkeypatch.setattr(escrow, "FEE", fee); monkeypatch.setattr(escrow, "BUYER_MARKUP", mk)
    f, b, lid, fh, bh = _mk(price, qty)
    r = client.post("/orders", json={"listing_id": lid, "buyer_id": b, "qty": qty}, headers=bh)
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    _release(oid, fh, bh)
    q = pricing_rules.quote(price, qty, 1.0, farmer_fee_pct=fee * 100, buyer_fee_pct=mk * 100)
    d = _released_detail(oid)
    assert d["farmer_gets"] == q["farmer_payout"]
    assert d["buyer_paid"] == q["buyer_pays"]
    assert d["platform_total"] == q["platform_revenue"]
    assert d["commission"] == round(q["gross"] - q["farmer_payout"], 2)
    mine = [o for o in client.get("/orders", params={"view": "farmer"}, headers=fh).json() if o["id"] == oid][0]
    assert mine["payout"] == q["farmer_payout"]
    s = client.get("/admin/summary", headers=admin(client)).json()
    assert s["platform_revenue"] == q["platform_revenue"]
    assert s["farmer_payouts"] == q["farmer_payout"]


def test_fee_trace_price30_qty200():
    f, b, lid, fh, bh = _mk(30, 200)
    oid = client.post("/orders", json={"listing_id": lid, "buyer_id": b, "qty": 200}, headers=bh).json()["id"]
    _release(oid, fh, bh)
    d = _released_detail(oid)
    assert (d["farmer_gets"], d["buyer_paid"], d["platform_total"]) == (5940.0, 6300.0, 360.0)


def test_admin_platform_revenue_is_sum_of_buyer_minus_amount():
    for p, q in [(30, 200), (41.7, 90), (8.25, 410)]:
        f, b, lid, fh, bh = _mk(p, q)
        oid = client.post("/orders", json={"listing_id": lid, "buyer_id": b, "qty": q}, headers=bh).json()["id"]
        _release(oid, fh, bh)
    with conn() as c:
        tot = c.execute("SELECT SUM(buyer_amount-amount) FROM orders WHERE state='RELEASED'").fetchone()[0]
    assert abs(client.get("/admin/summary", headers=admin(client)).json()["platform_revenue"] - tot) < 0.011


def test_dispute_case_reachable_over_http():
    f, b, lid, fh, bh = _mk(30, 200)
    oid = client.post("/orders", json={"listing_id": lid, "buyer_id": b, "qty": 200}, headers=bh).json()["id"]
    r = client.post(f"/orders/{oid}/dispute_case", json={"text": "Tomatoes arrived rotten after 2 days of delivery"}, headers=bh)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ESCALATE"
    cid = r.json()["case_id"]
    assert client.post(f"/cases/{cid}/resolve", json={"resolution": "Refund 50%"}, headers=admin(client)).status_code == 200
    r2 = client.post(f"/orders/{oid}/dispute_case", json={"text": "tomato came rotten, delivery took 2 days"}, headers=bh)
    assert r2.status_code == 200 and r2.json()["status"] == "AUTO"
    assert client.post(f"/orders/{oid}/nonsense", headers=bh).status_code == 404  # generic route still works


def test_no_oversell_under_concurrency():
    f, b, _, fh, bh = _mk(30, 1)
    for rnd in range(5):
        with conn() as c:
            lids = [c.execute("INSERT INTO listings(farmer_id,crop,qty,price,loc,status) VALUES(?,?,1,30,'Bangalore','ACTIVE')",
                              (f, "Tomato")).lastrowid for _ in range(20)]
        wins = []; barrier = threading.Barrier(8); lock = threading.Lock()

        def worker():
            for lid in lids:
                barrier.wait()
                try:
                    main._place(main.Order(listing_id=lid, buyer_id=b, qty=1))
                    with lock: wins.append(lid)
                except HTTPException:
                    pass
        ts = [threading.Thread(target=worker) for _ in range(8)]
        [t.start() for t in ts]; [t.join() for t in ts]
        assert sorted(wins) == sorted(lids)  # exactly one order per lot
        with conn() as c:
            assert c.execute("SELECT COUNT(*) FROM listings WHERE qty<0").fetchone()[0] == 0
            assert c.execute(f"SELECT COUNT(*) FROM orders WHERE listing_id IN ({','.join(map(str, lids))})").fetchone()[0] == 20
    assert escrow.verify_chain()[0]


def test_cancel_restores_stock_once():
    f, b, lid, fh, bh = _mk(30, 10)
    oid = client.post("/orders", json={"listing_id": lid, "buyer_id": b, "qty": 10}, headers=bh).json()["id"]
    with conn() as c:
        assert c.execute("SELECT qty FROM listings WHERE id=?", (lid,)).fetchone()[0] == 0
    assert client.post(f"/orders/{oid}/buyer_cancel", headers=bh).status_code == 200
    with conn() as c:
        assert c.execute("SELECT qty FROM listings WHERE id=?", (lid,)).fetchone()[0] == 10
    assert client.post(f"/orders/{oid}/buyer_cancel", headers=bh).status_code == 400  # second cancel: no double restore
    with conn() as c:
        assert c.execute("SELECT qty FROM listings WHERE id=?", (lid,)).fetchone()[0] == 10
