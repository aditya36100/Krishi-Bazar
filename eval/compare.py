"""Compare forecasters on the SAME rolling-origin split. Every model gets split-conformal
intervals from its own last `cal` rolling errors, so coverage/width are comparable.
LightGBM+ACI uses adaptive conformal inference (Gibbs & Candès 2021): alpha_t is updated
each step so long-run coverage converges to 1-alpha under distribution shift.
Usage: python -m eval.compare data/prices.csv Tomato Onion Potato Banana Carrot Mango"""
import sys, os, warnings, numpy as np, pandas as pd
from app.pricing import load, weekly, _ridge_predict
from app.lgbm_pricing import _make_features, _fit_quantile, K as LGBM_K
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


def _lgbm_aci_metrics(y, h, alpha, test, cal):
    """Rolling-origin evaluation for LightGBM with Adaptive Conformal Inference.
    At each test origin e:
      1. Train quantile LGBMs on y[:e] with lag+calendar features.
      2. Collect conformal residuals: gap = max(lo_pred - y_true, y_true - hi_pred, 0).
      3. ACI update: alpha_{t+1} = clip(alpha_t + gamma*(alpha - miss_t), 1e-6, 1-1e-6).
         Delayed feedback: at step e only outcomes up to y[e-1] are known, so the miss of step e-h is applied.
    Returns lists (ape, cov, wid) over the test window, same shape as baseline loop.
    """
    n = len(y)
    first = n - test - h - cal + 1
    gamma = 0.05                            # ACI step size (standard; Gibbs & Candes 2021)
    q_lo_fixed, q_hi_fixed = alpha / 2, 1 - alpha / 2

    # Pre-compute all predictions from first origin onward
    pts_mid, pts_lo, pts_hi, gaps = {}, {}, {}, {}
    for e in range(first, n - h + 1):
        idx_tr = list(range(LGBM_K, e - h + 1))
        if len(idx_tr) < 10:
            pts_mid[e] = y[e - 1]; pts_lo[e] = y[e - 1]; pts_hi[e] = y[e - 1]; gaps[e] = 0.0
            continue
        X_tr = _make_features(y, idx_tr, h)
        y_tr = np.array([y[i + h - 1] for i in idx_tr])
        m_lo  = _fit_quantile(X_tr, y_tr, q_lo_fixed)
        m_mid = _fit_quantile(X_tr, y_tr, 0.5)
        m_hi  = _fit_quantile(X_tr, y_tr, q_hi_fixed)
        x_new = _make_features(y, [e], h)
        pts_mid[e] = float(m_mid.predict(x_new)[0])
        pts_lo[e]  = float(m_lo.predict(x_new)[0])
        pts_hi[e]  = float(m_hi.predict(x_new)[0])
        y_true = y[e + h - 1]
        gaps[e] = max(pts_lo[e] - y_true, y_true - pts_hi[e], 0.0)

    ape, cov, wid = [], [], []
    alpha_t = alpha
    miss_at = {}   # step -> 0/1 miss, applied only once its outcome is known
    for e in range(n - test, n - h + 1):
        k_known = e - h   # the forecast made at step e-h has its outcome y[e-1] by now
        if k_known in miss_at:
            alpha_t = float(np.clip(alpha_t + gamma * (alpha - miss_at[k_known]), 1e-6, 1 - 1e-6))
        cal_gaps = [gaps[k] for k in range(e - h - cal + 1, e - h + 1) if k in gaps] or [0.0]
        q = np.quantile(cal_gaps, min(1.0, (1 - alpha_t) * (1 + 1 / len(cal_gaps))))
        lo_log = pts_lo[e] - q; hi_log = pts_hi[e] + q
        y_true = y[e + h - 1]
        a = np.exp(y_true); p = np.exp(pts_mid[e]); lo = np.exp(lo_log); hi = np.exp(hi_log)
        covered = lo <= a <= hi
        ape.append(abs(p - a) / a); cov.append(covered); wid.append((hi - lo) / a)
        miss_at[e] = 0.0 if covered else 1.0
    return ape, cov, wid


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
        # LightGBM + ACI
        print(f"  lgbm+aci {c}...", end=" ", flush=True)
        ape, cov, wid = _lgbm_aci_metrics(y, h, alpha, test, cal)
        print("done")
        rows.append(dict(crop=c, model="lgbm_aci", mape=100 * np.mean(ape), cover=100 * np.mean(cov), width=100 * np.mean(wid)))
    df = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(out), exist_ok=True); df.to_csv(out, index=False)
    all_models = list(MODELS) + ["lgbm_aci"]
    for col in ("mape", "cover", "width"):
        print(f"\n{col}%"); print(df.pivot(index="crop", columns="model", values=col)[all_models].round(1).to_string())

if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2:])
