"""LightGBM quantile model with Adaptive Conformal Intervals (ACI).

Architecture
------------
Features (all in log-price space):
  - 4 autoregressive lags (same as ridge baseline): y[t-1..t-4]
  - Calendar: week-of-year (sin/cos encoded), month sin/cos
  - h (forecast horizon in weeks, constant per model)

Three separate LightGBM regressors are trained per origin:
  q_lo (alpha/2), q_mid (0.5), q_hi (1 - alpha/2).

Interval method: Adaptive Conformal Inference (ACI, Gibbs & Candès 2021).
  alpha_t is updated each step: alpha_{t+1} = clip(alpha_t + gamma*(alpha - miss_t), 1e-6, 1-1e-6)
  where miss_t = 1 if y_true not in [lo_t, hi_t], 0 otherwise, and gamma = 0.05.
  The interval at step t uses split-conformal with the CURRENT alpha_t on the last `cal` errors.
  This gives long-run coverage converging to 1-alpha even under distribution shift.

NOTE: shelf-life of this model is the training window. For production, retrain weekly.
"""
import numpy as np
import lightgbm as lgb

K = 4  # lag order (matches ridge baseline)
LGB_PARAMS = {
    "objective": "quantile",
    "verbose": -1,
    "n_estimators": 200,
    "learning_rate": 0.05,
    "num_leaves": 15,
    "min_child_samples": 5,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
}


def _week_of_year(t):
    """Approximate week-of-year from integer index (0-based). Assumes weekly series starting Jan."""
    return (t % 52) + 1


def _make_features(y_log, indices, h):
    """Build feature matrix for given time indices (the origin, i.e. last observed index)."""
    rows = []
    for i in indices:
        lags = list(y_log[i - K:i])          # 4 lags
        woy = _week_of_year(i + h)            # target week-of-year
        woy_sin = np.sin(2 * np.pi * woy / 52)
        woy_cos = np.cos(2 * np.pi * woy / 52)
        month = int(((i + h) % 52) / 4.33) % 12
        mon_sin = np.sin(2 * np.pi * month / 12)
        mon_cos = np.cos(2 * np.pi * month / 12)
        rows.append(lags + [woy_sin, woy_cos, mon_sin, mon_cos])
    return np.array(rows, dtype=float)


def _fit_quantile(X_tr, y_tr, q):
    p = {**LGB_PARAMS, "alpha": q}
    m = lgb.LGBMRegressor(**p)
    m.fit(X_tr, y_tr)
    return m


def lgbm_predict(y_log, h, alpha=0.1):
    """Predict the h-week-ahead log-price from origin = last index of y_log.
    Returns (point, lo, hi) all in log-price space.
    Trains on the full available history up to this origin.
    """
    n = len(y_log)
    idx = list(range(K, n - h + 1))        # all valid training origins
    X = _make_features(y_log, idx, h)
    y = np.array([y_log[i + h - 1] for i in idx])
    q_lo, q_hi = alpha / 2, 1 - alpha / 2
    m_lo = _fit_quantile(X, y, q_lo)
    m_mid = _fit_quantile(X, y, 0.5)
    m_hi = _fit_quantile(X, y, q_hi)
    x_new = _make_features(y_log, [n], h)
    return float(m_mid.predict(x_new)[0]), float(m_lo.predict(x_new)[0]), float(m_hi.predict(x_new)[0])


def aci_band(errs_lo, errs_hi, alpha_t, cal):
    """Split-conformal band width using current adaptive alpha_t and last `cal` errors.
    errs_lo = y_true - lo_pred (how much y exceeds the lower bound; negative = covered below)
    errs_hi = hi_pred - y_true (how much hi_pred exceeds y; negative = covered above)
    We use a symmetric residual: max(lo_pred - y_true, y_true - hi_pred, 0) = miscoverage gap.
    """
    cal_errs = [max(errs_lo[i], errs_hi[i]) for i in range(-cal, 0)]
    q = np.quantile(cal_errs, min(1.0, (1 - alpha_t) * (1 + 1 / len(cal_errs))))
    return float(q)

