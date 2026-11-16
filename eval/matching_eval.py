"""Optimal (Hungarian) vs greedy matching on SYNTHETIC random instances (25 lots x 25 requests, 40% infeasible pairs)."""
import os, sys, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.matching import optimal, greedy, total, BIG

def run(trials=300, n=25, seed=0):
    rng = np.random.default_rng(seed)
    r = {"greedy": [0, 0.0], "optimal": [0, 0.0]}
    better = fewer = 0
    for _ in range(trials):
        C = rng.uniform(100, 1000, (n, n)); C[rng.random((n, n)) < 0.4] = BIG
        g, o = greedy(C), optimal(C)
        r["greedy"][0] += len(g); r["greedy"][1] += total(C, g)
        r["optimal"][0] += len(o); r["optimal"][1] += total(C, o)
        better += len(o) > len(g) or (len(o) == len(g) and total(C, o) < total(C, g) - 1e-9)
    print(f"trials={trials} optimal strictly better in {better} trials")
    for k, (m, t) in r.items():
        print(f"{k} avg_matches={m / trials:.2f} avg_cost_per_match={t / max(m, 1):.1f}")

if __name__ == "__main__":
    run()
