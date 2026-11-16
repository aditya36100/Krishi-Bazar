import sqlite3
from contextlib import contextmanager
from app import idempotency

def _factory():
    c = sqlite3.connect(":memory:", check_same_thread=False)
    idempotency.init(c)
    @contextmanager
    def conn_fn():
        yield c
        c.commit()
    return conn_fn

def test_new_busy_replay_release():
    f = _factory()
    assert idempotency.reserve(f, "k1", 7) == ("new", None)
    assert idempotency.reserve(f, "k1", 7) == ("busy", None)
    idempotency.complete(f, "k1", 7, {"id": 5, "state": "PLACED"})
    assert idempotency.reserve(f, "k1", 7) == ("replay", {"id": 5, "state": "PLACED"})
    assert idempotency.reserve(f, "k1", 8)[0] == "new"   # scoped per buyer
    assert idempotency.reserve(f, "k2", 7)[0] == "new"
    idempotency.release(f, "k2", 7)
    assert idempotency.reserve(f, "k2", 7)[0] == "new"
