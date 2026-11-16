"""Thompson sampling vs greedy-on-posterior-mean vs random: cumulative regret in a SIMULATION
(10 parties with true reliability ~ U(0.5, 0.95), 500 offers, 200 seeds). Not real user data."""
import numpy as np

def run(T=500, K=10, seeds=200):
    out = {"thompson": 0.0, "greedy_mean": 0.0, "random": 0.0}
    for s in range(seeds):
        p = np.random.default_rng(s).uniform(0.5, 0.95, K); best = p.max()
        for name in out:
            a, b, reg = np.full(K, 2.0), np.full(K, 2.0), 0.0
            r = np.random.default_rng(10_000 + s)
            for _ in range(T):
                k = int(np.argmax(r.beta(a, b))) if name == "thompson" else int(np.argmax(a / (a + b))) if name == "greedy_mean" else int(r.integers(K))
                win = r.random() < p[k]
                a[k] += win; b[k] += (not win); reg += best - p[k]
            out[name] += reg
    for k, v in out.items():
        print(f"{k} mean_cumulative_regret={v / seeds:.2f}")

if __name__ == "__main__":
    run()
