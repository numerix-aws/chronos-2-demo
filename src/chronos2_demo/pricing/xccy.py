"""XCCY swap valuation proxy.

Valuation is in USD: each leg discounted at its own ccy's swap rate at the
relevant tenor, FX-converted to USD via the panel's USD/XXX series.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from chronos2_demo.pricing.book import XCCYSwap

DEFAULT_FX_MAP = {
    "USD": None,         # already USD
    "EUR": "USDEUR",
    "JPY": "USDJPY",
    "GBP": "USDGBP",
    "CHF": "USDCHF",
    "CAD": "USDCAD",
}


def _years_remaining(maturity_date: str, valuation_dates: pd.DatetimeIndex) -> np.ndarray:
    mat = pd.Timestamp(maturity_date)
    delta = (mat - valuation_dates).days
    return np.maximum(delta / 365.25, 0.0)


def _to_usd(ccy: str, ccy_amount: np.ndarray, levels: pd.DataFrame,
            fx_map: dict[str, str | None]) -> np.ndarray:
    if fx_map[ccy] is None:
        return ccy_amount
    series = fx_map[ccy]
    return ccy_amount * levels[series].values


def value_swap_path(
    swap: XCCYSwap,
    levels: pd.DataFrame,
    ccy_to_usd_series_map: dict[str, str | None],
) -> np.ndarray:
    """Return USD MtM at each timestep of `levels` for one path.

    levels: DataFrame of absolute levels at each horizon date.
    ccy_to_usd_series_map: mapping each ccy to the panel column name for
                           USD-quoted FX rate (USDXXX). USD maps to None.
    """
    yrs = _years_remaining(swap.maturity_date, levels.index)
    pay_rate_col = f"{swap.pay_ccy}_{swap.pay_tenor}"
    rec_rate_col = f"{swap.receive_ccy}_{swap.receive_tenor}"
    pay_rate = levels[pay_rate_col].values if pay_rate_col in levels.columns else np.zeros(len(yrs))
    rec_rate = levels[rec_rate_col].values if rec_rate_col in levels.columns else np.zeros(len(yrs))

    # Receive leg PV in receive_ccy then in USD.
    pv_rec_native = swap.receive_notional * np.exp(-rec_rate * yrs)
    pv_rec_usd = _to_usd(swap.receive_ccy, pv_rec_native, levels, ccy_to_usd_series_map)
    # Pay leg PV in pay_ccy then in USD.
    pv_pay_native = swap.pay_notional * np.exp(-pay_rate * yrs)
    pv_pay_usd = _to_usd(swap.pay_ccy, pv_pay_native, levels, ccy_to_usd_series_map)

    return pv_rec_usd - pv_pay_usd
