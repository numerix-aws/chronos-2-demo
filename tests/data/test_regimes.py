import numpy as np
import pandas as pd
import pytest
from chronos2_demo.data import regimes


def _flat_panel(n=300):
    idx = pd.bdate_range("2020-01-02", periods=n)
    cols = ["USDEUR", "USDJPY", "USD_2Y", "USD_5Y", "USD_10Y"]
    return pd.DataFrame(np.zeros((n, 5)) + 1.0, index=idx, columns=cols)


def _shocked_panel(n=300):
    panel = _flat_panel(n)
    rng = np.random.default_rng(0)
    panel.iloc[200:230] += rng.normal(0, 0.1, size=(30, 5))
    return panel


def test_w_stress_in_unit_interval():
    panel = _shocked_panel()
    w = regimes.w_stress_series(panel, window=20)
    assert (w >= 0).all() and (w <= 1).all()


def test_w_stress_higher_in_shock_window():
    panel = _shocked_panel()
    w = regimes.w_stress_series(panel, window=20)
    calm = w.iloc[50:150].mean()
    shock = w.iloc[210:235].mean()
    assert shock > calm + 0.3


def test_label_thresholds():
    panel = _shocked_panel()
    labels = regimes.label_regimes(panel, window=20)
    assert set(labels.unique()) <= {"calm", "stress"}


def test_w_stress_features_exposed():
    panel = _shocked_panel()
    feats = regimes.regime_features(panel, window=20)
    assert {"rolling_vol", "rates_fx_corr", "vol_of_vol"} <= set(feats.columns)


def test_split_excludes_equity_and_credit_from_fx_rates():
    idx = pd.bdate_range("2020-01-02", periods=300)
    cols = ["USDEUR", "USDJPY", "USD_2Y", "USD_5Y", "SPX", "US_IG_OAS"]
    panel = pd.DataFrame(np.ones((300, 6)), index=idx, columns=cols)
    fx, rates = regimes._split_fx_rates(panel)
    assert list(fx.columns) == ["USDEUR", "USDJPY"]
    assert list(rates.columns) == ["USD_2Y", "USD_5Y"]
    # Equity/credit are in neither bucket.
    assert "SPX" not in fx.columns and "SPX" not in rates.columns
    assert "US_IG_OAS" not in fx.columns and "US_IG_OAS" not in rates.columns


def test_regime_features_still_three_columns_with_cross_asset():
    idx = pd.bdate_range("2020-01-02", periods=300)
    cols = ["USDEUR", "USD_2Y", "SPX", "US_HY_OAS"]
    rng = np.random.default_rng(0)
    panel = pd.DataFrame(1.0 + rng.normal(0, 0.01, size=(300, 4)).cumsum(axis=0),
                         index=idx, columns=cols)
    feats = regimes.regime_features(panel, window=20)
    assert {"rolling_vol", "rates_fx_corr", "vol_of_vol"} == set(feats.columns)
