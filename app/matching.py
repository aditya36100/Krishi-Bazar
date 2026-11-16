"""Farmer-lot to buyer-request matching. Optimal = min-cost assignment (Hungarian algorithm, scipy);
baseline = greedy cheapest-pair-first. Infeasible pairs cost BIG, so the optimal solution first maximises
the number of feasible matches, then minimises total cost. Whole lot only (no splitting).
Pure functions: nothing here touches the database yet."""
import numpy as np
from scipy.optimize import linear_sum_assignment

BIG = 1e9
RS_PER_KG_KM = 0.01   # ASSUMPTION (placeholder transport cost); tune with real data
UNKNOWN_KM = 300.0    # ASSUMPTION when a distance is unknown

def build_cost(listings, requests, dist_km):
    C = np.full((len(listings), len(requests)), BIG)
    for i, l in enumerate(listings):
        for j, r in enumerate(requests):
            if l["crop"] != r["crop"] or l["qty"] < r["min_kg"] or l["price"] > r["max_price"]:
                continue
            d = dist_km(l["loc"], r["loc"])
            d = UNKNOWN_KM if d is None else d
            C[i, j] = l["price"] * l["qty"] + RS_PER_KG_KM * d * l["qty"]
    return C

def optimal(C):
    r, c = linear_sum_assignment(C)
    return [(int(i), int(j)) for i, j in zip(r, c) if C[i, j] < BIG]

def greedy(C):
    pairs = sorted((C[i, j], i, j) for i in range(C.shape[0]) for j in range(C.shape[1]) if C[i, j] < BIG)
    ui, uj, out = set(), set(), []
    for _, i, j in pairs:
        if i not in ui and j not in uj:
            out.append((i, j)); ui.add(i); uj.add(j)
    return out

def total(C, pairs):
    return float(sum(C[i, j] for i, j in pairs))
