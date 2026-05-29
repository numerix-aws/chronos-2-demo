import numpy as np
import pandas as pd
import pytest
from chronos2_demo.diagnostics import coverage as cov
from chronos2_demo.types import PathSet


def _pathset(paths, weights=None, series=None, dates=None):
    n_paths, horizon, n_series = paths.shape
    weights = weights if weights is not None else np.full(n_paths, 1.0 / n_paths)
    series = series or [f"S{i}" for i in range(n_series)]
    dates = dates if dates is not None else pd.bdate_range("2022-07-01", periods=horizon)
    return PathSet(paths=paths, weights=weights, series=series, dates=dates,
                   source="parametric")


def test_band_coverage_perfect_when_all_realized_inside_band():
    rng = np.random.default_rng(0)
    n_paths, horizon, n_series = 1000, 30, 2
    paths = rng.normal(0, 1, size=(n_paths, horizon, n_series))
    ps = _pathset(paths)
    realized = pd.DataFrame(np.zeros((horizon, n_series)),
                            index=ps.dates, columns=ps.series)
    rate = cov.band_coverage(ps, realized, q_low=0.05, q_high=0.95)
    # Realized identically zero is well inside a (-1.64, 1.64) band on every series.
    assert (rate > 0.9).all()


def test_band_coverage_drops_when_realized_outside_band():
    rng = np.random.default_rng(0)
    n_paths, horizon, n_series = 1000, 30, 2
    paths = rng.normal(0, 1, size=(n_paths, horizon, n_series))
    ps = _pathset(paths)
    realized = pd.DataFrame(np.full((horizon, n_series), 5.0),
                            index=ps.dates, columns=ps.series)
    rate = cov.band_coverage(ps, realized, q_low=0.05, q_high=0.95)
    assert (rate < 0.1).all()


def test_regime_conditional_coverage_splits_by_w_stress():
    rng = np.random.default_rng(0)
    n_paths, horizon, n_series = 800, 20, 1
    paths = rng.normal(0, 1, size=(n_paths, horizon, n_series))
    ps = _pathset(paths)
    realized = pd.DataFrame(np.zeros((horizon, n_series)),
                            index=ps.dates, columns=ps.series)
    # First 10 timesteps calm, next 10 stress.
    w_stress = pd.Series(
        [0.1] * 10 + [0.9] * 10, index=ps.dates, name="w_stress"
    )
    out = cov.regime_conditional_coverage(ps, realized, w_stress,
                                          q_low=0.05, q_high=0.95,
                                          stress_threshold=0.7)
    assert set(out.keys()) == {"calm", "stress"}
    assert "S0" in out["calm"].index
    assert "S0" in out["stress"].index


def test_band_coverage_rejects_misaligned_realized():
    rng = np.random.default_rng(0)
    paths = rng.normal(0, 1, size=(50, 10, 2))
    ps = _pathset(paths)
    bad = pd.DataFrame(np.zeros((9, 2)),
                       index=pd.bdate_range("2022-07-01", periods=9),
                       columns=ps.series)
    with pytest.raises(ValueError, match="align"):
        cov.band_coverage(ps, bad, q_low=0.05, q_high=0.95)
