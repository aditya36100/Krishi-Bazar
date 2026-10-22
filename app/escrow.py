"""Escrow state machine + tamper-evident (hash-chained) audit ledger. Demo: no real money moves."""
import hashlib, json, datetime, os
from .db import conn

FEE = float(os.getenv("KS_FARMER_COMMISSION", "0.05"))  # taken from the farmer on delivered orders
BUYER_MARKUP = float(os.getenv("KS_BUYER_MARKUP", "0.05"))  # added to the price buyers see
GENESIS = "0" * 64
ALLOWED = {
    "PLACED": {"FUNDED", "CANCELLED"},
    "FUNDED": {"HARVESTED", "REFUNDED", "DISPUTED"},
    "HARVESTED": {"SHIPPED", "DISPUTED"},
    "SHIPPED": {"DELIVERED", "DISPUTED"},
    "DELIVERED": {"RELEASED", "DISPUTED"},
    "DISPUTED": {"RELEASED", "REFUNDED"},
}

def _log(c, oid, event, detail):
    row = c.execute("SELECT hash FROM ledger ORDER BY id DESC LIMIT 1").fetchone()
    prev = row["hash"] if row else GENESIS
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    d = json.dumps(detail, sort_keys=True)
    h = hashlib.sha256(json.dumps([oid, event, d, ts, prev]).encode()).hexdigest()
    c.execute("INSERT INTO ledger(order_id,event,detail,ts,prev_hash,hash) VALUES(?,?,?,?,?,?)",
              (oid, event, d, ts, prev, h))

def start(oid):
    with conn() as c:
        o = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        _log(c, oid, "PLACED", {"amount": o["amount"], "deposit_pct": o["deposit_pct"]})

def move(oid, new, detail=None):
    with conn() as c:
        o = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if not o:
            raise ValueError("no such order")
        if new not in ALLOWED.get(o["state"], set()):
            raise ValueError(f"{o['state']} -> {new} not allowed")
        c.execute("UPDATE orders SET state=? WHERE id=?", (new, oid))
        d = dict(detail or {}, amount=o["amount"])
        if new == "RELEASED":
            bp = o["buyer_amount"] or round(o["amount"] * (1 + BUYER_MARKUP), 2)
            d.update(commission=round(o["amount"] * FEE, 2), farmer_gets=round(o["amount"] * (1 - FEE), 2),
                     buyer_paid=bp, platform_total=round(bp - o["amount"] * (1 - FEE), 2))
        _log(c, oid, new, d)

def verify_chain():
    """Recompute every hash; returns (True, None) or (False, first_bad_ledger_id)."""
    prev = GENESIS
    with conn() as c:
        for r in c.execute("SELECT * FROM ledger ORDER BY id"):
            h = hashlib.sha256(json.dumps([r["order_id"], r["event"], r["detail"], r["ts"], prev]).encode()).hexdigest()
            if r["prev_hash"] != prev or r["hash"] != h:
                return False, r["id"]
            prev = r["hash"]
    return True, None


UNDO = {"HARVESTED": "FUNDED", "SHIPPED": "HARVESTED", "DELIVERED": "SHIPPED"}
UNDO_MINUTES = 15

def undo(oid):
    """Revert the latest non-money step within a short window. Appends an UNDO event; history is never deleted."""
    with conn() as c:
        o = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if not o:
            raise ValueError("no such order")
        prev = UNDO.get(o["state"])
        if not prev:
            raise ValueError(f"cannot undo from {o['state']} (money steps use cancel/refund/dispute)")
        last = c.execute("SELECT ts FROM ledger WHERE order_id=? ORDER BY id DESC LIMIT 1", (oid,)).fetchone()
        age = (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(last["ts"])).total_seconds() / 60
        if age > UNDO_MINUTES:
            raise ValueError(f"undo window ({UNDO_MINUTES} min) has passed - raise a dispute instead")
        c.execute("UPDATE orders SET state=? WHERE id=?", (prev, oid))
        _log(c, oid, "UNDO", {"from": o["state"], "to": prev})


CANCEL_MINUTES = 15
CANCEL_FEE = float(os.getenv("KS_CANCEL_FEE", "0.10"))  # share of the order value charged after the free window, capped at the deposit

def _cancel_charge(o, age):
    if age <= CANCEL_MINUTES or o["state"] != "FUNDED":
        return 0.0
    bp = o["buyer_amount"] or round(o["amount"] * (1 + BUYER_MARKUP), 2)
    return round(min(bp * CANCEL_FEE, bp * (o["deposit_pct"] or 0)), 2)

def cancel_preview(oid):
    with conn() as c:
        o = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        first = c.execute("SELECT ts FROM ledger WHERE order_id=? ORDER BY id LIMIT 1", (oid,)).fetchone()
    if not o or not first:
        return 0.0
    age = (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(first["ts"])).total_seconds() / 60
    return _cancel_charge(o, age)

def buyer_cancel(oid):
    """Buyer undoes an order. Free only while PLACED/FUNDED (farmer has not started) and within CANCEL_MINUTES of ordering."""
    with conn() as c:
        o = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if not o:
            raise ValueError("no such order")
        if o["state"] not in ("PLACED", "FUNDED"):
            raise ValueError(f"cannot cancel from {o['state']}: raise a dispute instead")
        first = c.execute("SELECT ts FROM ledger WHERE order_id=? ORDER BY id LIMIT 1", (oid,)).fetchone()
        age = (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(first["ts"])).total_seconds() / 60
        charge = _cancel_charge(o, age)
        new = "CANCELLED" if o["state"] == "PLACED" else "REFUNDED"
        c.execute("UPDATE orders SET state=? WHERE id=?", (new, oid))
        _log(c, oid, new, {"reason": "buyer cancelled" + ("" if age <= CANCEL_MINUTES else " after the free window"), "amount": o["amount"], "cancel_charge": charge})
        return charge
