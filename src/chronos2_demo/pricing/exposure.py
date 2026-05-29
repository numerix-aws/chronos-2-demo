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


def portfolio_mtm(book: Sequence[XCCYSwap], pathset: PathSet) -> np.ndarray:
    """Return (n_paths, horizon) USD MtM tensor for the whole book."""
    n_paths = pathset.n_paths
    horizon = pathset.horizon
    out = np.zeros((n_paths, horizon))
    for i in range(n_paths):
        levels_i = pd.DataFrame(
            pathset.paths[i],
            index=pathset.dates,
            columns=pathset.series,
        )
        for swap in book:
            out[i] += value_swap_path(swap, levels_i, DEFAULT_FX_MAP)
    return out
