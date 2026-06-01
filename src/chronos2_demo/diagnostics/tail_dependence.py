"""Exceedance correlation: Pearson correlation of log-return pairs
conditional on both being below a low quantile (lower-tail dependence).

Definition used here:
  joint_tail = (a < q_low(a)) & (b < q_low(b))
  return corrcoef(a[joint_tail], b[joint_tail])

This captures the "they crash together" effect that Gaussian copulas miss.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from chronos2_demo.types import PathSet


def _series_index(pathset: PathSet, name: str) -> int:
    if name not in pathset.series:
        raise KeyError(f"series {name!r} not in pathset.series={pathset.series}")
    return pathset.series.index(name)


def _path_log_returns_flat(pathset: PathSet, name: str) -> np.ndarray:
    j = _series_index(pathset, name)
    levels = pathset.paths[:, :, j]  # (n_paths, horizon)
    log_rets = np.diff(np.log(levels), axis=1)  # (n_paths, horizon-1)
    return log_rets.flatten()


def exceedance_correlation(
    pathset: PathSet,
    series_a: str,
    series_b: str,
    quantile: float = 0.05,
) -> float:
    a = _path_log_returns_flat(pathset, series_a)
    b = _path_log_returns_flat(pathset, series_b)
    return _exceedance_corr(a, b, quantile)


def realized_exceedance_correlation(
    realized: pd.DataFrame,
    series_a: str,
    series_b: str,
    quantile: float = 0.05,
) -> float:
    a = np.diff(np.log(realized[series_a].values))
    b = np.diff(np.log(realized[series_b].values))
    return _exceedance_corr(a, b, quantile)


def _exceedance_corr(a: np.ndarray, b: np.ndarray, quantile: float) -> float:
    qa_lo = np.quantile(a, quantile)
    qb_lo = np.quantile(b, quantile)
    mask = (a < qa_lo) & (b < qb_lo)
    if mask.sum() < 5:
        return float("nan")
    return float(np.corrcoef(a[mask], b[mask])[0, 1])
