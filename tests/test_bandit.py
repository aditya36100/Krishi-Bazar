import numpy as np
from app.bandit import thompson_pick, posterior

def test_posterior_prior():
    assert posterior(0, 0) == (2, 2)
    assert posterior(8, 10) == (10, 4)

def test_prefers_reliable_party():
    stats = {1: (95, 100), 2: (40, 100)}
    rng = np.random.default_rng(0)
    picks = [thompson_pick(stats, rng) for _ in range(200)]
    assert picks.count(1) > 190

def test_new_party_still_explored():
    stats = {1: (9, 10), 2: (0, 0)}
    rng = np.random.default_rng(0)
    assert 2 in [thompson_pick(stats, rng) for _ in range(200)]
