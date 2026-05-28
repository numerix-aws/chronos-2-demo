"""Joint alignment of heterogeneous public series into a canonical panel."""
from __future__ import annotations
from typing import Iterable
import pandas as pd


def align_panel(series_list: Iterable[pd.Series]) -> pd.DataFrame:
    """Inner-join Series on business-day index. Drops any row containing NaN.

    Returns a DataFrame indexed by sorted business days, columns sorted by name,
    no NaNs, no duplicate column names.
    """
    series_list = list(series_list)
    names = [s.name for s in series_list]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate column names: {names}")
    df = pd.concat(series_list, axis=1, join="inner")
    df = df.dropna(how="any")
    df = df.sort_index().sort_index(axis=1)
    df.index = pd.to_datetime(df.index)
    return df


def slice_lookback(panel: pd.DataFrame, as_of: str, lookback_days: int) -> pd.DataFrame:
    """Return the trailing `lookback_days` rows ending on or before `as_of`."""
    as_of_ts = pd.Timestamp(as_of)
    head = panel.loc[:as_of_ts]
    return head.tail(lookback_days)
