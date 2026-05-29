"""Parametric joint scenario engine.

Pipeline:
  1. fit_pca: standardize log-returns, extract orthogonal factor loadings.
  2. fit_factor_dynamics: AR(1) per factor (compact stand-in for Hull-White
     for rates factors; GBM-style for FX factors). One config knob.
  3. simulate: sample joint factor paths, project back through loadings,
     re-exponentiate to absolute level space.

This file is split across Tasks 7-10. Task 7 adds fit_pca only.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA


@dataclass(frozen=True)
class PCAFit:
    loadings: np.ndarray      # (n_series, k) orthonormal in feature space
    mean: np.ndarray          # (n_series,)
    std: np.ndarray           # (n_series,)
    explained_variance_ratio: np.ndarray  # (k,) descending
    series: list[str]


def fit_pca(panel: pd.DataFrame, n_components: int) -> PCAFit:
    """Standardize log-returns of `panel` and fit PCA.

    Returns loadings (n_series, k), mean, std (per series), and explained
    variance ratio. Loadings are taken as PCA components.T so that
    `standardized @ loadings == factor_scores`.
    """
    log_rets = np.log(panel).diff().dropna().values  # (T-1, n_series)
    mean = log_rets.mean(axis=0)
    std = log_rets.std(axis=0, ddof=1)
    # Guard against zero-variance series in tiny test panels.
    std = np.where(std < 1e-12, 1.0, std)
    standardized = (log_rets - mean) / std
    pca = PCA(n_components=n_components)
    pca.fit(standardized)
    loadings = pca.components_.T  # (n_series, k)
    return PCAFit(
        loadings=loadings,
        mean=mean,
        std=std,
        explained_variance_ratio=pca.explained_variance_ratio_,
        series=list(panel.columns),
    )
