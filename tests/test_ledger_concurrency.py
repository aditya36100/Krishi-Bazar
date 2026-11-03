import threading
import pytest
from app import db, escrow


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB", str(tmp_path / "t.db"))
    db.init()
    with db.conn() as c:
        for i in range(1, 41):
            c.execute("INSERT INTO orders(id,listing_id,buyer_id,qty,amount,state,deposit_pct) "
                      "VALUES(?,?,?,?,?,?,?)", (i, 1, 1, 10, 100.0, "PLACED", 0.2))
    return db


def _run(fns):
    errs = []
    def wrap(f):
        try:
            f()
        except Exception as e:
            errs.append(e)
    ts = [threading.Thread(target=wrap, args=(f,)) for f in fns]
    for t in ts: t.start()
    for t in ts: t.join()
    return errs


def test_chain_survives_concurrent_writes(fresh):
    _run([lambda i=i: escrow.start(i) for i in range(1, 41)])
    ok, bad = escrow.verify_chain()
    assert ok, f"hash chain forked at ledger id {bad}"
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) n FROM ledger").fetchone()["n"] == 40


def test_only_one_conflicting_transition_wins(fresh):
    with db.conn() as c:
        c.execute("UPDATE orders SET state='FUNDED' WHERE id=1")
    results = []
    def go(new):
        try:
            escrow.move(1, new); results.append(new)
        except ValueError:
            pass
    _run([lambda n=n: go(n) for n in ["HARVESTED", "REFUNDED"] * 10])
    assert len(results) == 1, f"{len(results)} conflicting transitions succeeded: {results}"
