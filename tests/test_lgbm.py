"""Unit tests for app/lgbm_pricing.py — feature builder and interval validity."""
import numpy as np
import pytest
from app.lgbm_pricing import _make_features, _fit_quantile, lgbm_predict, K


def _synthetic_series(n=120, seed=42):
    rng = np.random.default_rng(seed)
    y = np.cumsum(rng.normal(0, 0.02, n)) + 3.5   # log-price around e^3.5 ~ 33 Rs/kg
    return y


def test_make_features_shape():
    y = _synthetic_series()
    X = _make_features(y, list(range(K, K + 5)), h=2)
    assert X.shape == (5, K + 4), f"expected (5, {K+4}), got {X.shape}"


def test_make_features_lags_correct():
    y = np.arange(20, dtype=float)
    # origin index 4, h=1: lags should be y[0..3] = [0,1,2,3]
    X = _make_features(y, [4], h=1)
    assert list(X[0, :K]) == [0.0, 1.0, 2.0, 3.0]


def test_fit_quantile_produces_finite():
    y = _synthetic_series()
    idx = list(range(K, 80))
    X = _make_features(y, idx, h=2)
    y_tr = np.array([y[i + 1] for i in idx])
    m = _fit_quantile(X, y_tr, 0.5)
    pred = m.predict(_make_features(y, [80], h=2))
    assert np.isfinite(pred[0])


def test_lgbm_predict_lo_le_mid_le_hi():
    y = _synthetic_series(n=150)
    mid, lo, hi = lgbm_predict(y, h=2, alpha=0.1)
    assert lo <= mid <= hi, f"interval order violated: lo={lo:.4f} mid={mid:.4f} hi={hi:.4f}"


def test_lgbm_predict_in_log_price_range():
    """Log-prices for Indian agri: roughly 2.5–6 (Rs 12–400/kg)."""
    y = _synthetic_series(n=150)
    mid, lo, hi = lgbm_predict(y, h=2, alpha=0.1)
    assert 1.0 < mid < 8.0, f"mid={mid} out of plausible log-price range"
    assert hi > lo


def test_interval_covers_on_synthetic():
    """Over 30 rolling steps on synthetic data, ACI coverage should be > 50%
    (a very conservative check; real target is 90%)."""
    from eval.compare import _lgbm_aci_metrics
    y = _synthetic_series(n=200)
    ape, cov, wid = _lgbm_aci_metrics(y, h=2, alpha=0.1, test=30, cal=20)
    assert len(cov) == 29  # range(n-test, n-h+1) = range(170,199) = 29 steps for n=200, h=2
    assert np.mean(cov) > 0.5, f"coverage too low: {np.mean(cov):.2f}"
    assert all(w > 0 for w in wid)
