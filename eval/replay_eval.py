"""Does replay add detection beyond verify_chain()? SIMULATED tampering on a synthetic database:
(A) edit orders.state directly, (B) edit a ledger row's event. Each trial copies a 40-order database and tampers once."""
import os, sys, shutil, sqlite3, tempfile, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import db, escrow, replay

def build(path, n=40, seed=0):
    rnd = random.Random(seed)
    db.DB = path
    db.init()
    for _ in range(n):
        with db.conn() as c:
            oid = c.execute("INSERT INTO orders(listing_id,buyer_id,qty,amount,deposit_pct,created) VALUES(1,1,100,1000,0.3,'x')").lastrowid
        escrow.start(oid)
        state = "PLACED"
        for _ in range(rnd.randint(0, 4)):
            nxt = sorted(escrow.ALLOWED.get(state, set()))
            if not nxt:
                break
            state = rnd.choice(nxt)
            escrow.move(oid, state)

def run(trials=200, seed=1):
    rnd = random.Random(seed)
    d = tempfile.mkdtemp()
    base = os.path.join(d, "base.db")
    build(base)
    res = {"A": [0, 0, 0], "B": [0, 0, 0]}   # [trials, chain_detects, chain_or_replay_detects]
    for t in range(trials):
        kind = "A" if t % 2 == 0 else "B"
        p = os.path.join(d, "t.db"); shutil.copy(base, p); db.DB = p
        with db.conn() as c:
            if kind == "A":
                oid, s = rnd.choice(c.execute("SELECT id, state FROM orders").fetchall())
                c.execute("UPDATE orders SET state=? WHERE id=?", (rnd.choice([x for x in escrow.ALLOWED if x != s]), oid))
            else:
                rid, ev = rnd.choice(c.execute("SELECT id, event FROM ledger").fetchall())
                c.execute("UPDATE ledger SET event=? WHERE id=?", ("RELEASED" if ev != "RELEASED" else "FUNDED", rid))
        chain = not escrow.verify_chain()[0]
        both = chain or not replay.check()["ok"]
        res[kind][0] += 1; res[kind][1] += chain; res[kind][2] += both
    names = {"A": "edit orders.state directly", "B": "edit a ledger row"}
    for k, (n, a, b) in res.items():
        print(f"{names[k]}: trials={n} verify_chain detects {a}/{n}; chain+replay detects {b}/{n}")

if __name__ == "__main__":
    run()
