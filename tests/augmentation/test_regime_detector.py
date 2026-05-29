import numpy as np
import pandas as pd
import pytest
from chronos2_demo.augmentation import regime_detector as rd


def _flat_panel(n=300):
    idx = pd.bdate_range("2020-01-02", periods=n)
    cols = ["USDEUR", "USDJPY", "USD_2Y", "USD_5Y", "USD_10Y"]
    return pd.DataFrame(np.ones((n, 5)) + 1e-3, index=idx, columns=cols)


def _shocked_panel(n=300, shock_start=200, shock_len=30):
    panel = _flat_panel(n)
    rng = np.random.default_rng(0)
    panel.iloc[shock_start:shock_start + shock_len] += rng.normal(0, 0.1,
                                                                  size=(shock_len, 5))
    return panel


def test_current_w_stress_is_unit_interval_value():
    panel = _shocked_panel()
    snap = rd.current_w_stress(panel, as_of=panel.index[-1].strftime("%Y-%m-%d"),
                               window=20)
    assert isinstance(snap, rd.RegimeSnapshot)
    assert 0.0 <= snap.w_stress <= 1.0
    assert {"rolling_vol", "rates_fx_corr", "vol_of_vol"} <= set(snap.features)


def test_current_w_stress_is_high_in_shock_period():
    panel = _shocked_panel(shock_start=200, shock_len=30)
    in_shock_date = panel.index[225].strftime("%Y-%m-%d")
    calm_date = panel.index[100].strftime("%Y-%m-%d")
    w_shock = rd.current_w_stress(panel, in_shock_date, window=20).w_stress
    w_calm = rd.current_w_stress(panel, calm_date, window=20).w_stress
    assert w_shock > w_calm + 0.2


def test_current_w_stress_rejects_unknown_as_of():
    panel = _flat_panel()
    with pytest.raises(KeyError):
        rd.current_w_stress(panel, "2099-01-01", window=20)
