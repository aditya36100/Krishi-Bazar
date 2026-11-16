"""Isolation Forest vs robust z-score baseline on SYNTHETIC injected price errors.
Train on the first 70% of each crop's days; test on the last 30%. 5% of test points get their price
multiplied by a factor. Real farmer errors may differ, so report this as a controlled test only."""
import os, sys, numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.anomaly import daily, feats, train_matrix, fit_if, fit_baseline, baseline_flag, MIN_HIST

CSV = os.path.join(os.path.dirname(__file__), "..", "data", "prices.csv")
FACTORS = [0.3, 0.5, 1.8, 2.5, 3.0]
MILD = {0.5, 1.8}

def run(seed=0):
    d = pd.read_csv(CSV, parse_dates=["date"])
    rng = np.random.default_rng(seed)
    tp = {"IF": 0, "BL": 0}; fp = dict(tp); fn = dict(tp)
    n_clean = n_inj = n_mild = 0; hit_mild = {"IF": 0, "BL": 0}
    for crop in sorted(d["commodity"].unique()):
        y = daily(d, crop).values
        if len(y) < MIN_HIST + 200:
            continue
        cut = int(len(y) * 0.7)
        Xtr = train_matrix(y, end=cut)
        m_if, p_bl = fit_if(Xtr, seed), fit_baseline(Xtr)
        rows, lab, fac = [], [], []
        for i in range(cut, len(y)):
            f = rng.choice(FACTORS) if rng.random() < 0.05 else 1.0
            rows.append(feats(float(y[i]) * f, y[:i])); lab.append(f != 1.0); fac.append(f)
        X, lab, fac = np.array(rows), np.array(lab), np.array(fac)
        pred = {"IF": m_if.predict(X) == -1, "BL": baseline_flag(X, p_bl)}
        n_inj += lab.sum(); n_clean += (~lab).sum()
        mild = np.isin(fac, list(MILD)); n_mild += mild.sum()
        for k, p in pred.items():
            tp[k] += (p & lab).sum(); fp[k] += (p & ~lab).sum(); fn[k] += (~p & lab).sum()
            hit_mild[k] += (p & mild).sum()
    out = {}
    for k in ("IF", "BL"):
        pr = tp[k] / max(tp[k] + fp[k], 1); rc = tp[k] / max(tp[k] + fn[k], 1)
        out[k] = dict(precision=pr, recall=rc, f1=2 * pr * rc / max(pr + rc, 1e-9),
                      false_alarm_rate=fp[k] / n_clean, mild_recall=hit_mild[k] / n_mild)
    return out, int(n_inj), int(n_clean)

if __name__ == "__main__":
    res, ni, nc = run()
    print(f"injected={ni} clean={nc}")
    for k, v in res.items():
        print(k, " ".join(f"{a}={b:.3f}" for a, b in v.items()))
