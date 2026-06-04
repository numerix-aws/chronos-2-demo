"""Portfolio MtM and exposure metrics.

This file is split across Tasks 20-21. Task 20 adds portfolio_mtm.
Task 21 adds compute_ee, compute_pfe, compute_es.
"""
from __future__ import annotations
from typing import Sequence
import numpy as np
import pandas as pd

from chronos2_demo.pricing.book import XCCYSwap
from chronos2_demo.pricing.xccy import value_swap_path, DEFAULT_FX_MAP
from chronos2_demo.types import PathSet
from chronos2_demo.pricing.instruments import (
    EquityForward, CDSProtection, value_equity_forward_path, value_cds_protection_path,
)


def portfolio_mtm(
    book: Sequence[XCCYSwap],
    pathset: PathSet,
    equity_forwards: Sequence[EquityForward] = (),
    cds_protection: Sequence[CDSProtection] = (),
) -> np.ndarray:
    """Return (n_paths, horizon) USD MtM tensor for the whole cross-asset book."""
    n_paths = pathset.n_paths
    horizon = pathset.horizon
    out = np.zeros((n_paths, horizon))
    for i in range(n_paths):
        levels_i = pd.DataFrame(
            pathset.paths[i], index=pathset.dates, columns=pathset.series,
        )
        for swap in book:
            out[i] += value_swap_path(swap, levels_i, DEFAULT_FX_MAP)
        for fwd in equity_forwards:
            out[i] += value_equity_forward_path(fwd, levels_i, DEFAULT_FX_MAP)
        for cds in cds_protection:
            out[i] += value_cds_protection_path(cds, levels_i)
    return out


def compute_ee(mtm: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Weighted expected exposure: sum_i w_i * max(MtM_{i,t}, 0)."""
    exposure = np.maximum(mtm, 0.0)
    return weights @ exposure  # (horizon,)


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    """Linear-interpolation weighted quantile."""
    order = np.argsort(values)
    v = values[order]
    w = weights[order]
    cw = np.cumsum(w)
    cw /= cw[-1]
    return float(np.interp(q, cw, v))


def compute_pfe(mtm: np.ndarray, weights: np.ndarray, q: float = 0.975) -> np.ndarray:
    exposure = np.maximum(mtm, 0.0)
    horizon = exposure.shape[1]
    return np.array([_weighted_quantile(exposure[:, t], weights, q) for t in range(horizon)])


def compute_es(mtm: np.ndarray, weights: np.ndarray, q: float = 0.975) -> np.ndarray:
    """Weighted expected shortfall above quantile q."""
    exposure = np.maximum(mtm, 0.0)
    horizon = exposure.shape[1]
    out = np.empty(horizon)
    for t in range(horizon):
        v = exposure[:, t]
        threshold = _weighted_quantile(v, weights, q)
        mask = v >= threshold
        if not mask.any():
            out[t] = threshold
            continue
        w = weights[mask]
        out[t] = float((v[mask] * w).sum() / w.sum())
    return out


def compute_metrics(book: Sequence[XCCYSwap], pathset: PathSet,
                    q: float = 0.975,
                    equity_forwards: Sequence[EquityForward] = (),
                    cds_protection: Sequence[CDSProtection] = ()) -> dict:
    mtm = portfolio_mtm(book, pathset, equity_forwards=equity_forwards,
                        cds_protection=cds_protection)
    return {
        "ee":      compute_ee(mtm, pathset.weights),
        "pfe_975": compute_pfe(mtm, pathset.weights, q=q),
        "es_975":  compute_es(mtm, pathset.weights, q=q),
        "dates":   pathset.dates,
    }
