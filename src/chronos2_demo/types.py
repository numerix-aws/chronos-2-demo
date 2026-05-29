"""Shared data types every module agrees on. Keep this file small."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
import numpy as np
import pandas as pd

Source = Literal["parametric", "chronos2", "blended", "chronos2_conditional"]


@dataclass(frozen=True)
class PathSet:
    """Shared path-set container.

    paths: ndarray (n_paths, horizon, n_series), in absolute level space.
    weights: ndarray (n_paths,), non-negative, sums to 1.
    series: ordered list of series names, matches paths last axis.
    dates: pandas DatetimeIndex of length `horizon`.
    source: which engine produced these paths.
    """
    paths: np.ndarray
    weights: np.ndarray
    series: list[str]
    dates: pd.DatetimeIndex
    source: Source

    def __post_init__(self) -> None:
        n_paths, horizon, n_series = self.paths.shape
        if self.weights.shape != (n_paths,):
            raise ValueError("weights shape must match n_paths")
        if (self.weights < 0).any():
            raise ValueError("weights must be non-negative")
        if not np.isclose(self.weights.sum(), 1.0):
            raise ValueError("weights must sum to 1")
        if len(self.series) != n_series:
            raise ValueError("shape mismatch: series length must equal paths.shape[-1]")
        if len(self.dates) != horizon:
            raise ValueError("shape mismatch: dates length must equal paths.shape[1]")

    @property
    def n_paths(self) -> int:
        return self.paths.shape[0]

    @property
    def horizon(self) -> int:
        return self.paths.shape[1]

    @property
    def n_series(self) -> int:
        return self.paths.shape[2]
