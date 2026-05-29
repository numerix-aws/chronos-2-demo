"""Regime-conditional band coverage diagnostic.

Given a PathSet and aligned realized series, compute the fraction of timesteps
at which the realized value falls inside the [q_low, q_high] weighted-quantile
band of the path samples — overall and split by an external w_stress series.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from chronos2_demo.types import PathSet


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    order = np.argsort(values)
    v = values[order]
    w = weights[order]
    cw = np.cumsum(w)
    cw /= cw[-1]
    return float(np.interp(q, cw, v))


def _band_per_series_per_t(
    pathset: PathSet, q_low: float, q_high: float
) -> tuple[np.ndarray, np.ndarray]:
    """Return (lo, hi) bands shaped (horizon, n_series)."""
    horizon, n_series = pathset.horizon, pathset.n_series
    lo = np.empty((horizon, n_series))
    hi = np.empty((horizon, n_series))
    for t in range(horizon):
        for j in range(n_series):
            v = pathset.paths[:, t, j]
            lo[t, j] = _weighted_quantile(v, pathset.weights, q_low)
            hi[t, j] = _weighted_quantile(v, pathset.weights, q_high)
    return lo, hi


def band_coverage(
    pathset: PathSet,
    realized: pd.DataFrame,
    q_low: float = 0.05,
    q_high: float = 0.95,
) -> pd.Series:
    """Per-series fraction of timesteps with realized inside the [q_low, q_high] band."""
    if not realized.index.equals(pathset.dates):
        raise ValueError("realized index must align with pathset.dates")
    if list(realized.columns) != pathset.series:
        raise ValueError("realized columns must match pathset.series")
    lo, hi = _band_per_series_per_t(pathset, q_low, q_high)
    rv = realized.values
    inside = (rv >= lo) & (rv <= hi)
    rates = inside.mean(axis=0)
    return pd.Series(rates, index=pathset.series, name="band_coverage")


def regime_conditional_coverage(
    pathset: PathSet,
    realized: pd.DataFrame,
    w_stress: pd.Series,
    q_low: float = 0.05,
    q_high: float = 0.95,
    stress_threshold: float = 0.7,
) -> dict[str, pd.Series]:
    """Split coverage by w_stress regime and return {'calm': ..., 'stress': ...}."""
    if not realized.index.equals(pathset.dates):
        raise ValueError("realized index must align with pathset.dates")
    if not w_stress.index.equals(pathset.dates):
        raise ValueError("w_stress index must align with pathset.dates")
    lo, hi = _band_per_series_per_t(pathset, q_low, q_high)
    rv = realized.values
    inside = (rv >= lo) & (rv <= hi)  # (horizon, n_series)
    stress_mask = (w_stress.values >= stress_threshold)
    calm_mask = ~stress_mask

    def _frac(mask: np.ndarray) -> pd.Series:
        if not mask.any():
            return pd.Series(np.full(pathset.n_series, np.nan), index=pathset.series)
        return pd.Series(inside[mask].mean(axis=0), index=pathset.series)

    return {"calm": _frac(calm_mask), "stress": _frac(stress_mask)}
