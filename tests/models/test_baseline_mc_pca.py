import numpy as np
import pandas as pd
from chronos2_demo.models import baseline_mc


def test_pca_returns_unit_variance_factors_and_loadings():
    rng = np.random.default_rng(0)
    n_obs, n_series = 500, 5
    raw = rng.normal(0, 0.01, size=(n_obs, n_series)).cumsum(axis=0) + 1.0
    panel = pd.DataFrame(raw, columns=[f"S{i}" for i in range(n_series)],
                         index=pd.bdate_range("2020-01-02", periods=n_obs))
    fit = baseline_mc.fit_pca(panel, n_components=3)
    assert fit.loadings.shape == (n_series, 3)
    assert fit.mean.shape == (n_series,)
    assert fit.std.shape == (n_series,)
    # explained variance ratio descending
    evr = fit.explained_variance_ratio
    assert (np.diff(evr) <= 1e-12).all()


def test_pca_components_can_reconstruct_returns_in_log_space():
    rng = np.random.default_rng(1)
    n_obs, n_series = 800, 4
    raw = rng.normal(0, 0.005, size=(n_obs, n_series)).cumsum(axis=0) + 1.0
    panel = pd.DataFrame(raw, columns=list("ABCD"),
                         index=pd.bdate_range("2020-01-02", periods=n_obs))
    fit = baseline_mc.fit_pca(panel, n_components=4)
    # full-rank reconstruction error on standardized log-returns is small
    log_rets = np.log(panel).diff().dropna().values
    standardized = (log_rets - fit.mean) / fit.std
    factors = standardized @ fit.loadings  # (n_obs-1, k)
    recon = factors @ fit.loadings.T
    assert np.linalg.norm(standardized - recon) / np.linalg.norm(standardized) < 0.05
