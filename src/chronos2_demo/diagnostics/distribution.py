"""KS and energy-distance summaries between path-set marginals and a realized sample."""
from __future__ import annotations
import numpy as np
from scipy import stats
from chronos2_demo.types import PathSet


def _series_index(pathset: PathSet, name: str) -> int:
    if name not in pathset.series:
        raise KeyError(f"series {name!r} not in pathset.series={pathset.series}")
    return pathset.series.index(name)


def _path_marginal(pathset: PathSet, t: int, series: str) -> np.ndarray:
    j = _series_index(pathset, series)
    return pathset.paths[:, t, j]


def ks_at_step(
    pathset: PathSet, t: int, series: str, realized_sample: np.ndarray
) -> float:
    """Two-sample KS statistic between path-set marginal at t and realized."""
    sample = _path_marginal(pathset, t, series)
    stat, _ = stats.ks_2samp(sample, realized_sample)
    return float(stat)


def energy_distance_at_step(
    pathset: PathSet, t: int, series: str, realized_sample: np.ndarray
) -> float:
    """Two-sample energy distance (Szekely & Rizzo)."""
    sample = _path_marginal(pathset, t, series)
    return float(stats.energy_distance(sample, realized_sample))
