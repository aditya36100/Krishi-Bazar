import numpy as np
from app.matching import optimal, greedy, total, BIG, build_cost

def test_optimal_beats_greedy_on_classic_case():
    C = np.array([[1.0, 2.0], [2.0, 100.0]])
    assert total(C, greedy(C)) == 101.0
    assert total(C, optimal(C)) == 4.0

def test_max_cardinality_and_infeasible_dropped():
    C = np.array([[1.0, BIG], [1.0, BIG]])
    assert len(optimal(C)) == 1
    assert all(C[i, j] < BIG for i, j in optimal(C))

def test_build_cost_rules():
    L = [{"crop": "Tomato", "qty": 500, "price": 20, "loc": "A"}]
    R = [{"crop": "Tomato", "min_kg": 100, "max_price": 25, "loc": "B"}, {"crop": "Onion", "min_kg": 100, "max_price": 25, "loc": "B"},
         {"crop": "Tomato", "min_kg": 800, "max_price": 25, "loc": "B"}, {"crop": "Tomato", "min_kg": 100, "max_price": 10, "loc": "B"}]
    C = build_cost(L, R, lambda a, b: 100.0)
    assert C[0, 0] < BIG and (C[0, 1:] == BIG).all()
