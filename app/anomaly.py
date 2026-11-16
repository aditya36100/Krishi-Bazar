"""Price anomaly check (roadmap 3): is an asking price out of line with the crop's recent market?
Model: Isolation Forest on 3 features. Baseline: robust z-score of log(price / 28-day median).
Flags only; the admin decides. Never blocks a listing."""
import numpy as np, pandas as pd
from sklearn.ensemble import IsolationForest

MIN_HIST = 366

def daily(d, crop):
    s = d[d["commodity"] == crop].set_index("date")["modal_price"].resample("D").mean()
    return s.interpolate(limit=7).dropna()

def feats(p, hist):
    m28, m365 = np.median(hist[-28:]), np.median(hist[-365:])
    vol = np.std(np.diff(np.log(hist[-28:])))
    return [np.log(p / m28), np.log(p / m365), vol]

def train_matrix(y, start=None, end=None):
    y = np.asarray(y, dtype=float)
    lo = max(MIN_HIST, start or 0)
    hi = end or len(y)
    return np.array([feats(y[i], y[:i]) for i in range(lo, hi)])

def fit_if(X, seed=0):
    return IsolationForest(n_estimators=200, contamination=0.02, random_state=seed).fit(X)

def fit_baseline(X):
    med = np.median(X[:, 0])
    mad = 1.4826 * np.median(np.abs(X[:, 0] - med)) or 1e-6
    return med, mad

def baseline_flag(X, params, thr=3.5):
    med, mad = params
    return np.abs((X[:, 0] - med) / mad) > thr

class PriceChecker:
    def __init__(self, df):
        self.df, self.cache = df, {}

    def _model(self, crop):
        if crop not in self.cache:
            y = daily(self.df, crop).values
            if len(y) <= MIN_HIST + 50:
                self.cache[crop] = None
            else:
                self.cache[crop] = (y, fit_if(train_matrix(y)))
        return self.cache[crop]

    def check(self, crop, price):
        m = self._model(crop)
        if m is None or price <= 0:
            return {"flag": False, "level": "UNKNOWN", "reason": "not enough history to judge"}
        y, model = m
        x = np.array([feats(float(price), y)])
        flag = bool(model.predict(x)[0] == -1)
        m28 = float(np.median(y[-28:]))
        pct = (price / m28 - 1) * 100
        side = "above" if pct > 0 else "below"
        return {"flag": flag, "level": "REVIEW" if flag else "OK", "score": round(float(model.decision_function(x)[0]), 4),
                "recent_median": round(m28, 2),
                "reason": f"{abs(pct):.0f}% {side} the last 28-day median of Rs {m28:.2f}/kg (history ends at the last data date)"}
