"""Phase 2: every protected route rejects missing and wrong-role tokens; owners only touch their own data."""
import pytest
from fastapi.testclient import TestClient
from app import main, auth
from app.db import conn
from tests.helpers import register, admin, bearer, PW

client = TestClient(main.app)

ADMIN_ONLY = [
    ("get", "/admin/summary", None), ("get", "/admin/settings", None), ("post", "/admin/settings", {}),
    ("get", "/cases", None), ("post", "/cases/1/resolve", {"resolution": "x"}), ("post", "/cases/1/wrong", None),
    ("post", "/orders/1/fault/1", None), ("post", "/tickets/1/schedule?visit_date=2030-01-01", None),
    ("post", "/tickets/1/reject", None), ("post", "/tickets/1/approve", {"grade": "A", "qty": 100, "price": 10, "agreed": True}),
    ("post", "/listings/1/unpublish", None), ("get", "/tickets/1/photo_flags", None),
]
LOGIN_ONLY = [("get", "/me", None), ("get", "/users", None), ("get", "/orders", None), ("get", "/listings", None),
              ("get", "/reliability/1", None), ("get", "/media/1", None), ("get", "/orders/1/ledger", None),
              ("post", "/orders/1/fund", None), ("post", "/orders/1/dispute_case", {"text": "x"}),
              ("get", "/subscription/1", None), ("post", "/subscribe/1/plus", None),
              ("post", "/tickets/1/cancel", None), ("post", "/tickets/1/submit", None), ("delete", "/tickets/1", None)]
ROLE_ONLY = [("post", "/orders", {"listing_id": 1, "buyer_id": 1, "qty": 1}, "farmer"),
             ("post", "/tickets", {"farmer_id": 1, "crop": "Tomato", "qty": 200, "location": "x", "phone": "9876543210",
                                   "pref_date": "2030-01-01", "pref_slot": "Morning (8-11 am)"}, "buyer"),
             ("get", "/tickets", None, "buyer")]


def call(method, path, body, hdr=None):
    return client.request(method.upper(), path, json=body, headers=hdr or {})


@pytest.mark.parametrize("method,path,body", ADMIN_ONLY)
def test_admin_routes(method, path, body):
    assert call(method, path, body).status_code == 401
    assert call(method, path, body, register(client, "farmer")[1]).status_code == 403
    assert call(method, path, body, register(client, "buyer")[1]).status_code == 403
    assert call(method, path, body, admin(client)).status_code not in (401, 403)


@pytest.mark.parametrize("method,path,body", LOGIN_ONLY)
def test_login_required(method, path, body):
    assert call(method, path, body).status_code == 401


@pytest.mark.parametrize("method,path,body,bad_role", ROLE_ONLY)
def test_wrong_role_blocked(method, path, body, bad_role):
    assert call(method, path, body).status_code == 401
    assert call(method, path, body, register(client, bad_role)[1]).status_code == 403


def test_public_routes_need_no_login():
    for p in ("/meta", "/ledger/verify", "/"):
        assert client.get(p).status_code == 200, p


def test_register_login_me_and_rules():
    uid, h = register(client, "farmer", name="Asha")
    me = client.get("/me", headers=h).json()
    assert me["id"] == uid and me["role"] == "farmer"
    base = {"name": "A", "loc": "x", "phone": "9123456780", "password": PW, "buyer_type": ""}
    assert client.post("/users", json={**base, "role": "admin"}).status_code == 400          # nobody registers as admin
    assert client.post("/users", json={**base, "role": "farmer", "password": "short"}).status_code == 400
    assert client.post("/users", json={**base, "role": "farmer", "phone": ""}).status_code == 400
    assert client.post("/users", json={**base, "role": "farmer"}).status_code == 200
    assert client.post("/users", json={**base, "role": "farmer"}).status_code == 409         # phone already used
    assert client.post("/login", json={"phone": "9123456780", "password": PW}).status_code == 200
    assert client.post("/login", json={"phone": "9123456780", "password": "wrong-password"}).status_code == 401
    assert client.post("/login", json={"phone": "9000000000", "password": PW}).status_code == 401
    with conn() as c:  # a password is never stored in clear text
        assert c.execute("SELECT COUNT(*) FROM users WHERE password_hash=?", (PW,)).fetchone()[0] == 0
        assert c.execute("SELECT password_hash FROM users WHERE id=?", (uid,)).fetchone()[0].startswith("scrypt$")
    assert "password" not in str(client.get("/users", headers=admin(client)).json()).lower()


def test_tampered_and_expired_tokens(monkeypatch):
    uid, h = register(client, "buyer")
    tok = h["Authorization"][7:]
    body, sig = tok.split(".")
    assert client.get("/me", headers=bearer(body + "." + sig[:-2] + "AA")).status_code == 401
    assert client.get("/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    real = auth.time.time()
    monkeypatch.setattr(auth.time, "time", lambda: real + auth.TTL + 10)
    assert client.get("/me", headers=h).status_code == 401


def _order(price=30, qty=100):
    f, fh = register(client, "farmer"); b, bh = register(client, "buyer")
    with conn() as c:
        lid = c.execute("INSERT INTO listings(farmer_id,crop,qty,price,loc,status) VALUES(?,?,?,?,?,'ACTIVE')", (f, "Tomato", qty, price, "Bangalore")).lastrowid
    oid = client.post("/orders", json={"listing_id": lid, "buyer_id": b, "qty": qty}, headers=bh).json()["id"]
    return f, fh, b, bh, oid


def test_order_ownership():
    f, fh, b, bh, oid = _order()
    _, other_b = register(client, "buyer"); _, other_f = register(client, "farmer")
    assert client.post(f"/orders/{oid}/fund", headers=other_b).status_code == 403
    assert client.post(f"/orders/{oid}/fund", headers=fh).status_code == 403           # farmer cannot fund
    assert client.post(f"/orders/{oid}/fund", headers=bh).status_code == 200
    assert client.post(f"/orders/{oid}/harvest", headers=other_f).status_code == 403
    assert client.post(f"/orders/{oid}/harvest", headers=bh).status_code == 403        # buyer cannot harvest
    assert client.post(f"/orders/{oid}/harvest", headers=fh).status_code == 200
    assert client.post(f"/orders/{oid}/buyer_cancel", headers=other_b).status_code == 403
    assert client.post(f"/orders/{oid}/dispute_case", json={"text": "x"}, headers=other_b).status_code == 403
    assert client.get(f"/orders/{oid}/ledger", headers=other_b).status_code == 403
    assert client.post(f"/orders/{oid}/dispute", headers=bh).status_code == 200
    assert client.post(f"/orders/{oid}/release", headers=bh).status_code == 403       # disputed: admin only
    assert client.post(f"/orders/{oid}/refund", headers=fh).status_code == 403
    assert client.post(f"/orders/{oid}/refund", headers=admin(client)).status_code == 200


def test_order_lists_are_private_and_buyer_id_is_not_trusted():
    f, fh, b, bh, oid = _order()
    _, other_b = register(client, "buyer"); _, other_f = register(client, "farmer")
    assert [o["id"] for o in client.get("/orders?view=buyer", headers=bh).json()] == [oid]
    assert client.get("/orders?view=buyer", headers=other_b).json() == []
    assert client.get("/orders?view=farmer", headers=other_f).json() == []
    assert [o["id"] for o in client.get("/orders?view=admin", headers=fh).json()] == [oid]  # view is forced to the caller's role
    assert [o["id"] for o in client.get("/orders", headers=admin(client)).json()] == [oid]
    with conn() as c:
        lid = c.execute("INSERT INTO listings(farmer_id,crop,qty,price,loc,status) VALUES(?,?,?,?,?,'ACTIVE')", (f, "Tomato", 100, 30, "Bangalore")).lastrowid
    ob, obh = register(client, "buyer")
    spoof = client.post("/orders", json={"listing_id": lid, "buyer_id": b, "qty": 100}, headers=obh).json()["id"]
    with conn() as c:
        assert c.execute("SELECT buyer_id FROM orders WHERE id=?", (spoof,)).fetchone()[0] == ob  # taken from the token


def test_ledger_detail_masked_for_non_admin():
    f, fh, b, bh, oid = _order()
    assert all(r["detail"] == "(admin only)" for r in client.get(f"/orders/{oid}/ledger?view=admin", headers=bh).json())
    assert all(r["detail"] != "(admin only)" for r in client.get(f"/orders/{oid}/ledger", headers=admin(client)).json())


def test_users_listing_and_tickets_are_scoped():
    fa, fha = register(client, "farmer"); fb, fhb = register(client, "farmer")
    assert [u["id"] for u in client.get("/users", headers=fha).json()] == [fa]
    assert {u["id"] for u in client.get("/users", headers=admin(client)).json()} >= {fa, fb}
    t = client.post("/tickets", json={"farmer_id": fb, "crop": "Tomato", "qty": 200, "location": "x", "phone": "9876543210",
                                      "pref_date": "2030-01-01", "pref_slot": "Morning (8-11 am)"}, headers=fha)
    assert t.status_code == 200, t.text
    tid = t.json()["id"]
    with conn() as c:
        assert c.execute("SELECT farmer_id FROM tickets WHERE id=?", (tid,)).fetchone()[0] == fa  # taken from the token
    assert client.post(f"/tickets/{tid}/cancel", headers=fhb).status_code == 403
    assert client.delete(f"/tickets/{tid}", headers=fhb).status_code == 403
    assert client.post(f"/tickets/{tid}/submit", headers=fhb).status_code == 403
    with conn() as c:
        c.execute("UPDATE tickets SET status='OPEN' WHERE id=?", (tid,))  # a draft cannot be cancelled, an open ticket can
    assert client.post(f"/tickets/{tid}/cancel", headers=fha).status_code == 200


def test_media_needs_owner_or_admin(tmp_path):
    fa, fha = register(client, "farmer"); fb, fhb = register(client, "farmer")
    p = tmp_path / "x.jpg"; p.write_bytes(b"x")
    with conn() as c:
        tid = c.execute("INSERT INTO tickets(farmer_id,crop,qty,status) VALUES(?,?,?,?)", (fa, "Tomato", 200, "OPEN")).lastrowid
        mid = c.execute("INSERT INTO ticket_media(ticket_id,kind,path,filename,size) VALUES(?,?,?,?,1)", (tid, "photo", str(p), "x.jpg")).lastrowid
    assert client.get(f"/media/{mid}").status_code == 401
    assert client.get(f"/media/{mid}", headers=fhb).status_code == 403
    assert client.get(f"/media/{mid}", headers=fha).status_code == 200
    tok = fha["Authorization"][7:]
    assert client.get(f"/media/{mid}?t={tok}").status_code == 200  # <img src> cannot send headers, so ?t= works
