import numpy as np
import pandas as pd
import pytest
from chronos2_demo.pricing import xccy
from chronos2_demo.pricing.book import XCCYSwap


def _swap():
    return XCCYSwap(
        id="t", pay_ccy="EUR", pay_tenor="5Y", pay_notional=10_000_000,
        receive_ccy="USD", receive_tenor="5Y", receive_notional=10_800_000,
        spot_at_inception_quote_per_base=1.08,
        trade_date="2022-01-03", maturity_date="2027-01-03",
    )


def _path_levels():
    """Single path: 252 days of daily levels for the relevant series."""
    idx = pd.bdate_range("2022-01-04", periods=252)
    return pd.DataFrame({
        "USDEUR": np.full(252, 1.08),
        "USD_5Y": np.full(252, 0.025),
        "EUR_5Y": np.full(252, 0.005),
        "USD_2Y": np.full(252, 0.020),
        "EUR_2Y": np.full(252, 0.000),
        "USDJPY": np.full(252, 0.0088),
        "JPY_5Y": np.full(252, 0.000),
        "JPY_2Y": np.full(252, 0.000),
        "JPY_10Y": np.full(252, 0.001),
        "USD_10Y": np.full(252, 0.030),
        "EUR_10Y": np.full(252, 0.010),
        "USDGBP": np.full(252, 1.35),
        "GBP_2Y": np.full(252, 0.010),
        "GBP_5Y": np.full(252, 0.015),
        "GBP_10Y": np.full(252, 0.020),
    }, index=idx)


def test_value_swap_at_inception_is_near_zero():
    swap = _swap()
    levels = _path_levels()
    val = xccy.value_swap_path(swap, levels, ccy_to_usd_series_map=xccy.DEFAULT_FX_MAP)
    # USD MtM at day 0 with rates that make the legs ~par should be small
    # relative to notional.
    notional_usd = swap.pay_notional * 1.08
    assert abs(val[0]) < 0.10 * notional_usd


def test_value_swap_responds_to_fx_shock():
    swap = _swap()
    levels = _path_levels().copy()
    levels["USDEUR"] = 1.20  # EUR appreciates strongly
    val_shocked = xccy.value_swap_path(swap, levels, ccy_to_usd_series_map=xccy.DEFAULT_FX_MAP)
    val_baseline = xccy.value_swap_path(_swap(), _path_levels(),
                                        ccy_to_usd_series_map=xccy.DEFAULT_FX_MAP)
    # Receiving USD, paying EUR → EUR strength reduces USD MtM.
    assert val_shocked[0] < val_baseline[0]


def test_value_swap_responds_to_rates_shock():
    swap = _swap()
    levels = _path_levels().copy()
    levels["USD_5Y"] = 0.060  # large USD rate hike
    val_shocked = xccy.value_swap_path(swap, levels, ccy_to_usd_series_map=xccy.DEFAULT_FX_MAP)
    val_baseline = xccy.value_swap_path(_swap(), _path_levels(),
                                        ccy_to_usd_series_map=xccy.DEFAULT_FX_MAP)
    # Receiving USD fixed → higher discount rate reduces PV of receive leg.
    assert val_shocked[0] < val_baseline[0]


def test_value_swap_returns_full_horizon():
    swap = _swap()
    levels = _path_levels()
    val = xccy.value_swap_path(swap, levels, ccy_to_usd_series_map=xccy.DEFAULT_FX_MAP)
    assert val.shape == (252,)
