"""Thompson sampling over parties using the same Beta(2,2)-prior success/failure counts as reliability.py.
Use it to decide whom to offer a lot to first: it mostly picks reliable parties but keeps exploring
new ones. Baseline (greedy on posterior mean) is compared in eval/bandit_eval.py."""
import numpy as np
from .db import conn

def posterior(s, n, a0=2, b0=2):
    return a0 + s, b0 + n - s

def stats_for(party_ids):
    out = {}
    with conn() as c:
        for pid in party_ids:
            r = c.execute("SELECT COALESCE(SUM(ok),0) s, COUNT(*) n FROM outcomes WHERE party_id=?", (pid,)).fetchone()
            out[pid] = (int(r["s"]), int(r["n"]))
    return out

def thompson_pick(stats, rng=None):
    rng = rng or np.random.default_rng()
    best, best_v = None, -1.0
    for pid, (s, n) in stats.items():
        a, b = posterior(s, n)
        v = rng.beta(a, b)
        if v > best_v:
            best, best_v = pid, v
    return best

def pick_party(party_ids, rng=None):
    return thompson_pick(stats_for(party_ids), rng) if party_ids else None
