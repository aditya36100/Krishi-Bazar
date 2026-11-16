"""Event replay: rebuild every order's state from the hash-chained ledger and compare it with the orders table.
It catches tampering that verify_chain() cannot: someone editing orders.state directly leaves the ledger
(and so its hashes) untouched. Read-only: it only reports, it never repairs."""
import json
from .db import conn
from .escrow import ALLOWED, UNDO

ALL_STATES = set(ALLOWED) | set().union(*ALLOWED.values())

def replay(rows):
    """rows: ledger rows in id order (dicts with id, order_id, event, detail). Returns (states, violations, unknown_events)."""
    states, bad, unknown = {}, [], {}
    for r in rows:
        oid, ev, cur = r["order_id"], r["event"], states.get(r["order_id"])
        if ev == "PLACED":
            if cur is not None:
                bad.append((r["id"], oid, "PLACED twice"))
            states[oid] = "PLACED"
        elif ev == "UNDO":
            d = json.loads(r["detail"] or "{}")
            if cur != d.get("from") or UNDO.get(cur) != d.get("to"):
                bad.append((r["id"], oid, f"bad UNDO from {cur}"))
            states[oid] = d.get("to", cur)
        elif ev in ALL_STATES:
            if cur is None or ev not in ALLOWED.get(cur, set()):
                bad.append((r["id"], oid, f"illegal {cur} -> {ev}"))
            states[oid] = ev
        else:
            unknown[ev] = unknown.get(ev, 0) + 1
    return states, bad, unknown

def check():
    with conn() as c:
        rows = [dict(r) for r in c.execute("SELECT id, order_id, event, detail FROM ledger ORDER BY id")]
        orders = [(r["id"], r["state"]) for r in c.execute("SELECT id, state FROM orders")]
    states, bad, unknown = replay(rows)
    mismatches = [(oid, states[oid], s) for oid, s in orders if oid in states and states[oid] != s]
    missing = [oid for oid, _ in orders if oid not in states]
    return {"ok": not mismatches and not bad, "mismatches": mismatches, "violations": bad,
            "orders_without_ledger": missing, "unknown_events": unknown}
