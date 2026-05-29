"""Pointwise regime snapshot used by the blender at a single as-of date.

This is a thin adapter over data/regimes.py: it computes the rolling features
on the full panel, then returns the value AT the given as-of date along with
the displayable feature dict.
"""
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd

from chronos2_demo.data.regimes import regime_features, w_stress_series


@dataclass(frozen=True)
class RegimeSnapshot:
    as_of: pd.Timestamp
    w_stress: float
    features: dict[str, float]


def current_w_stress(panel: pd.DataFrame, as_of: str, window: int = 20) -> RegimeSnapshot:
    as_of_ts = pd.Timestamp(as_of)
    feats = regime_features(panel, window=window)
    if as_of_ts not in feats.index:
        raise KeyError(f"as_of {as_of} not in computed feature index")
    w = w_stress_series(panel, window=window)
    return RegimeSnapshot(
        as_of=as_of_ts,
        w_stress=float(w.loc[as_of_ts]),
        features={k: float(v) for k, v in feats.loc[as_of_ts].items()},
    )
