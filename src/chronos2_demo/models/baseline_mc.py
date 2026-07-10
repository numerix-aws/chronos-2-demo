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


# Levels are clipped to this positive floor before taking logs so that rate
# series that touch or cross zero (e.g. EUR_2Y, JPY_2Y) don't poison the whole
# return panel with NaNs. On strictly-positive panels this is a no-op.
_LEVEL_FLOOR = 1e-6


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
    log_rets = np.log(panel.clip(lower=_LEVEL_FLOOR)).diff().dropna().values  # (T-1, n_series)
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


@dataclass(frozen=True)
class FactorDynamics:
    phi: np.ndarray    # (k,) AR(1) coefficient per factor
    sigma: np.ndarray  # (k,) innovation std per factor


def fit_factor_dynamics(panel: pd.DataFrame, pca: PCAFit) -> FactorDynamics:
    """Fit AR(1) per factor: f_t = phi * f_{t-1} + sigma * eps_t."""
    log_rets = np.log(panel.clip(lower=_LEVEL_FLOOR)).diff().dropna().values
    standardized = (log_rets - pca.mean) / pca.std
    factors = standardized @ pca.loadings  # (T-1, k)
    k = factors.shape[1]
    phi = np.empty(k)
    sigma = np.empty(k)
    for j in range(k):
        x = factors[:-1, j]
        y = factors[1:, j]
        denom = (x * x).sum()
        phi_j = (x * y).sum() / denom if denom > 1e-12 else 0.0
        # Clamp to (-0.999, 0.999) for stability.
        phi_j = float(np.clip(phi_j, -0.999, 0.999))
        resid = y - phi_j * x
        sigma_j = float(np.sqrt(max((resid * resid).mean(), 1e-12)))
        phi[j] = phi_j
        sigma[j] = sigma_j
    return FactorDynamics(phi=phi, sigma=sigma)


def _sample_factor_paths(
    dyn: FactorDynamics,
    n_paths: int,
    horizon: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Draw (n_paths, horizon, k) factor paths starting from f_0 = 0."""
    k = dyn.phi.shape[0]
    eps = rng.standard_normal(size=(n_paths, horizon, k))
    paths = np.empty_like(eps)
    f_prev = np.zeros((n_paths, k))
    for t in range(horizon):
        f_t = dyn.phi * f_prev + dyn.sigma * eps[:, t, :]
        paths[:, t, :] = f_t
        f_prev = f_t
    return paths


from chronos2_demo.types import PathSet


def simulate_baseline(
    panel: pd.DataFrame,
    as_of: str,
    horizon: int,
    n_paths: int,
    n_components: int,
    seed: int = 0,
) -> PathSet:
    """Simulate joint factor paths and project to absolute-level space.

    Steps:
      1. Fit PCA + factor dynamics on `panel` history up to and including `as_of`.
      2. Sample (n_paths, horizon, k) factor paths.
      3. Project to standardized log-return space via loadings.T.
      4. Reverse standardization, cumulate, exponentiate, multiply by S_{as_of}.
    """
    # as_of may fall on a weekend/holiday (e.g. the demo default 2020-03-15,
    # a Sunday); snap to the last trading date at or before it instead of
    # failing a strict label lookup.
    history = panel.loc[:pd.Timestamp(as_of)]
    if history.empty:
        raise ValueError(f"as_of {as_of} predates the panel history")
    as_of_eff = history.index[-1]
    pca = fit_pca(history, n_components=n_components)
    dyn = fit_factor_dynamics(history, pca)
    rng = np.random.default_rng(seed)
    factor_paths = _sample_factor_paths(dyn, n_paths, horizon, rng)  # (N, H, k)

    # Project factors back to standardized log-return space.
    log_rets = np.einsum("nhk,sk->nhs", factor_paths, pca.loadings)
    # De-standardize: x = log_ret * std + mean.
    log_rets = log_rets * pca.std + pca.mean
    # Cumulate to get log levels relative to S_{as_of}.
    cum_log = np.cumsum(log_rets, axis=1)
    s0 = panel.loc[as_of_eff].values  # (n_series,)
    levels = s0 * np.exp(cum_log)

    horizon_dates = pd.bdate_range(
        start=as_of_eff + pd.tseries.offsets.BDay(1), periods=horizon
    )
    weights = np.full(n_paths, 1.0 / n_paths)
    return PathSet(
        paths=levels,
        weights=weights,
        series=list(panel.columns),
        dates=horizon_dates,
        source="parametric",
    )
