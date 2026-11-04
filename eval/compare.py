"""Compare forecasters on the SAME rolling-origin split. Every model gets split-conformal
intervals from its own last `cal` rolling errors, so coverage/width are comparable.
Usage: python -m eval.compare data/prices.csv Tomato Onion Potato Banana Carrot Mango"""
import sys, os, warnings, numpy as np, pandas as pd
from app.pricing import load, weekly, _ridge_predict
warnings.filterwarnings("ignore")

def p_naive(y, h):
    return y[-1]

def p_seasonal(y, h):
    # value of the same week one year before the target week
    i = len(y) + h - 1 - 52
    return y[i] if i >= 0 else y[-1]

def p_ridge(y, h):
    return _ridge_predict(y, h)

def p_ets(y, h):
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    m = ExponentialSmoothing(y, trend="add", damped_trend=True).fit()
    return float(m.forecast(h)[-1])

def p_arima(y, h):
    from statsmodels.tsa.arima.model import ARIMA
    m = ARIMA(y, order=(1, 1, 1)).fit()
    return float(m.forecast(h)[-1])

MODELS = {"naive": p_naive, "seasonal": p_seasonal, "ridge": p_ridge, "ets": p_ets, "arima": p_arima}

def run(csv, crops, h=2, alpha=0.1, test=40, cal=26, out="results/compare.csv"):
    d = load(csv); rows = []
    for c in crops:
        y = np.log(np.asarray(weekly(d, c), dtype=float)); n = len(y)
        first = n - test - h - cal + 1
        if first < 60:
            print(f"skip {c}: only {n} weeks"); continue
        for name, fn in MODELS.items():
            pt = {e: fn(y[:e], h) for e in range(first, n - h + 1)}
            err = {e: abs(y[e + h - 1] - p) for e, p in pt.items()}
            ape, cov, wid = [], [], []
            for e in range(n - test, n - h + 1):
                cals = [err[k] for k in range(e - h - cal + 1, e - h + 1)]
                q = np.quantile(cals, min(1.0, (1 - alpha) * (1 + 1 / len(cals))))
                a = np.exp(y[e + h - 1]); p, lo, hi = np.exp(pt[e]), np.exp(pt[e] - q), np.exp(pt[e] + q)
                ape.append(abs(p - a) / a); cov.append(lo <= a <= hi); wid.append((hi - lo) / a)
            rows.append(dict(crop=c, model=name, mape=100 * np.mean(ape), cover=100 * np.mean(cov), width=100 * np.mean(wid)))
    df = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(out), exist_ok=True); df.to_csv(out, index=False)
    for col in ("mape", "cover", "width"):
        print(f"\n{col}%"); print(df.pivot(index="crop", columns="model", values=col)[list(MODELS)].round(1).to_string())

if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2:])
