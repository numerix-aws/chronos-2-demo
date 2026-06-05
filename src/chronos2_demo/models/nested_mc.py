"""Nested Monte Carlo exposure engine — BENCHMARK REFERENCE ONLY.

Outer factor scenarios × inner revaluation sub-paths at each exposure date.
This is the cost the FM-path + closed-form pipeline avoids; it is timed against
that pipeline in scripts/benchmark_latency.py. It is deliberately NOT wired into
pricing.exposure.compute_metrics — the demo prices closed-form. See spec §8/§11.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence
import numpy as np
import pandas as pd

from chronos2_demo.types import PathSet
from chronos2_demo.pricing.book import XCCYSwap
from chronos2_demo.pricing.xccy import value_swap_path, DEFAULT_FX_MAP
from chronos2_demo.pricing.instruments import (
    EquityForward, CDSProtection, value_equity_forward_path, value_cds_protection_path,
)
from chronos2_demo.pricing.exposure import compute_pfe


@dataclass(frozen=True)
class NestedResult:
    pfe: np.ndarray          # (horizon,)
    n_revaluations: int


def _reval_one(levels_row: pd.DataFrame, swaps, equity_forwards, cds_protection) -> float:
    """Sum USD MtM of the whole book for a single 1-row levels frame."""
    pv = 0.0
    for s in swaps:
        pv += value_swap_path(s, levels_row, DEFAULT_FX_MAP)[0]
    for f in equity_forwards:
        pv += value_equity_forward_path(f, levels_row, DEFAULT_FX_MAP)[0]
    for c in cds_protection:
        pv += value_cds_protection_path(c, levels_row)[0]
    return pv


def run_nested(
    pathset: PathSet,
    swaps: Sequence[XCCYSwap],
    equity_forwards: Sequence[EquityForward] = (),
    cds_protection: Sequence[CDSProtection] = (),
    n_inner: int = 200,
    inner_vol: float = 0.01,
    q: float = 0.975,
    seed: int = 0,
) -> NestedResult:
    """Nested-MC PFE: at each (outer, t), average book PV over n_inner GBM bumps."""
    rng = np.random.default_rng(seed)
    n_paths, horizon, n_series = pathset.paths.shape
    sim_pv = np.empty((n_paths, horizon))
    n_revals = 0
    for i in range(n_paths):
        for t in range(horizon):
            state = pathset.paths[i, t, :]                       # (n_series,)
            bumps = rng.standard_normal(size=(n_inner, n_series))
            inner_levels = state * np.exp(inner_vol * bumps - 0.5 * inner_vol**2)
            pvs = np.empty(n_inner)
            date_t = pathset.dates[t:t + 1]
            for k in range(n_inner):
                row = pd.DataFrame(inner_levels[k:k + 1], index=date_t,
                                   columns=pathset.series)
                pvs[k] = _reval_one(row, swaps, equity_forwards, cds_protection)
                n_revals += 1
            sim_pv[i, t] = pvs.mean()
    pfe = compute_pfe(sim_pv, pathset.weights, q=q)
    return NestedResult(pfe=pfe, n_revaluations=n_revals)


def nested_pfe(pathset, swaps, equity_forwards=(), cds_protection=(),
               n_inner=200, inner_vol=0.01, q=0.975, seed=0) -> np.ndarray:
    """Convenience: just the PFE curve from run_nested."""
    return run_nested(pathset, swaps, equity_forwards, cds_protection,
                      n_inner=n_inner, inner_vol=inner_vol, q=q, seed=seed).pfe
