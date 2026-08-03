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


def align_covariates_to_panel(
    covariates: pd.DataFrame,
    panel_index: pd.Index,
) -> pd.DataFrame:
    """Carry past covariate observations onto the canonical market dates."""
    source = covariates.copy()
    source.index = pd.DatetimeIndex(pd.to_datetime(source.index)).normalize()
    target = pd.DatetimeIndex(pd.to_datetime(panel_index)).normalize()
    if source.index.has_duplicates or target.has_duplicates:
        raise ValueError("covariate and market panel dates must be unique")
    expanded = source.reindex(source.index.union(target)).sort_index().ffill()
    aligned = expanded.reindex(target)
    if aligned.isna().any(axis=None):
        raise ValueError("covariates cannot cover the market panel without future data")
    return aligned
