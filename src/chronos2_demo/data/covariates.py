"""Exogenous covariates fed only to Chronos-2 (VIX / MOVE / WTI)."""
from __future__ import annotations
import pandas as pd
from chronos2_demo.data import fetch
from chronos2_demo.data.align import align_panel

_FRED_COV = {"VIX": "VIXCLS", "WTI": "DCOILWTICO"}


def _fetch_one(name: str, api_key: str) -> pd.Series:
    """Indirection so tests can patch a single function. MOVE is Yahoo-only."""
    if name == "MOVE":
        return fetch.fetch_yahoo_series("^MOVE").rename("MOVE")
    return fetch.fetch_fred_series(_FRED_COV[name], api_key=api_key).rename(name)


def load_covariates(api_key: str = "") -> pd.DataFrame:
    series = [_fetch_one(n, api_key) for n in ("VIX", "MOVE", "WTI")]
    return align_panel(series)
