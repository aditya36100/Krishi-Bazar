"""Idempotency keys for POST /orders: a retry with the same Idempotency-Key header returns the first
response instead of creating a second order. Keys are scoped per buyer. States: new / replay / busy."""
import json, sqlite3, datetime

def init(c):
    c.execute("CREATE TABLE IF NOT EXISTS idempotency(key TEXT PRIMARY KEY, buyer_id INT, response TEXT, created TEXT)")

def _k(key, buyer_id):
    return f"{buyer_id}:{key.strip()[:200]}"

def reserve(conn_fn, key, buyer_id):
    k = _k(key, buyer_id)
    with conn_fn() as c:
        try:
            c.execute("INSERT INTO idempotency(key,buyer_id,response,created) VALUES(?,?,NULL,?)",
                      (k, buyer_id, datetime.datetime.now().isoformat()))
            return "new", None
        except sqlite3.IntegrityError:
            r = c.execute("SELECT response FROM idempotency WHERE key=?", (k,)).fetchone()
    if r and r[0]:
        return "replay", json.loads(r[0])
    return "busy", None

def complete(conn_fn, key, buyer_id, resp):
    with conn_fn() as c:
        c.execute("UPDATE idempotency SET response=? WHERE key=?", (json.dumps(resp), _k(key, buyer_id)))

def release(conn_fn, key, buyer_id):
    with conn_fn() as c:
        c.execute("DELETE FROM idempotency WHERE key=? AND response IS NULL", (_k(key, buyer_id),))
