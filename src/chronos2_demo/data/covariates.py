"""Exogenous covariates fed only to Chronos-2 (VIX / MOVE / WTI)."""
from __future__ import annotations
import pandas as pd
from chronos2_demo.data import fetch
from chronos2_demo.data.align import align_panel


def _fetch_one(name: str) -> pd.Series:
    """Indirection so tests can patch a single function."""
    fred_map = {"VIX": "VIXCLS", "MOVE": "MOVE", "WTI": "DCOILWTICO"}
    return fetch.fetch_fred_series(fred_map[name], api_key="").rename(name)


def load_covariates() -> pd.DataFrame:
    series = [_fetch_one(n) for n in ("VIX", "MOVE", "WTI")]
    return align_panel(series)
