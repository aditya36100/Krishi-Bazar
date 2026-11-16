import sqlite3
import pytest
from app import db, escrow, replay

@pytest.fixture
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", str(tmp_path / "t.db"))
    db.init()

def _order():
    with db.conn() as c:
        oid = c.execute("INSERT INTO orders(listing_id,buyer_id,qty,amount,deposit_pct,created) VALUES(1,1,100,1000,0.3,'x')").lastrowid
    escrow.start(oid)
    return oid

def test_replay_matches_table_including_undo(fresh):
    oid = _order()
    for s in ("FUNDED", "HARVESTED"):
        escrow.move(oid, s)
    escrow.undo(oid)
    r = replay.check()
    assert r["ok"] and r["mismatches"] == [] and r["violations"] == []

def test_direct_table_edit_is_caught_but_chain_still_verifies(fresh):
    oid = _order()
    escrow.move(oid, "FUNDED")
    with db.conn() as c:
        c.execute("UPDATE orders SET state='RELEASED' WHERE id=?", (oid,))
    assert escrow.verify_chain()[0] is True
    r = replay.check()
    assert not r["ok"] and r["mismatches"] == [(oid, "FUNDED", "RELEASED")]

def test_illegal_transition_in_rows():
    rows = [{"id": 1, "order_id": 1, "event": "PLACED", "detail": "{}"},
            {"id": 2, "order_id": 1, "event": "SHIPPED", "detail": "{}"}]
    states, bad, unknown = replay.replay(rows)
    assert bad and "illegal PLACED -> SHIPPED" in bad[0][2]
