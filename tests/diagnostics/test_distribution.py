import numpy as np
import pandas as pd
import pytest
from chronos2_demo.diagnostics import distribution as ds
from chronos2_demo.types import PathSet


def _pathset_normal(loc=0.0, scale=1.0, n_paths=2000, horizon=10, n_series=1, seed=0):
    rng = np.random.default_rng(seed)
    paths = rng.normal(loc, scale, size=(n_paths, horizon, n_series))
    weights = np.full(n_paths, 1.0 / n_paths)
    return PathSet(paths=paths, weights=weights,
                   series=[f"S{i}" for i in range(n_series)],
                   dates=pd.bdate_range("2022-07-01", periods=horizon),
                   source="parametric")


def test_ks_zero_when_distributions_match():
    ps = _pathset_normal(seed=0)
    realized_sample = np.random.default_rng(1).normal(0, 1, size=2000)
    stat = ds.ks_at_step(ps, t=5, series="S0", realized_sample=realized_sample)
    assert stat < 0.1


def test_ks_large_when_distributions_differ():
    ps = _pathset_normal(loc=0.0, scale=1.0, seed=0)
    shifted = np.random.default_rng(1).normal(5.0, 1.0, size=2000)
    stat = ds.ks_at_step(ps, t=5, series="S0", realized_sample=shifted)
    assert stat > 0.5


def test_energy_distance_nonnegative_and_zero_on_self():
    ps = _pathset_normal(seed=0)
    sample = ps.paths[:, 5, 0]
    val = ds.energy_distance_at_step(ps, t=5, series="S0", realized_sample=sample)
    assert val >= 0
    assert val < 0.05  # near-zero — same sample


def test_distribution_metrics_reject_unknown_series():
    ps = _pathset_normal(seed=0)
    with pytest.raises(KeyError):
        ds.ks_at_step(ps, t=0, series="Z",
                      realized_sample=np.zeros(10))
