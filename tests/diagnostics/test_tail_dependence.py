import numpy as np
import pandas as pd
import pytest
from chronos2_demo.diagnostics import tail_dependence as td
from chronos2_demo.types import PathSet


def _pathset_from_log_rets(log_rets: np.ndarray, series: list[str]) -> PathSet:
    """Cumulate log returns into levels, build a PathSet."""
    levels = np.exp(log_rets.cumsum(axis=1))
    n_paths, horizon, _ = levels.shape
    return PathSet(
        paths=levels,
        weights=np.full(n_paths, 1.0 / n_paths),
        series=series,
        dates=pd.bdate_range("2022-07-01", periods=horizon),
        source="parametric",
    )


def test_exceedance_corr_high_when_pair_co_moves_in_tail():
    rng = np.random.default_rng(0)
    n_paths, horizon = 4000, 20
    common = rng.normal(0, 0.02, size=(n_paths, horizon, 1))
    a = common + rng.normal(0, 0.005, size=(n_paths, horizon, 1))
    b = common + rng.normal(0, 0.005, size=(n_paths, horizon, 1))
    log_rets = np.concatenate([a, b], axis=2)
    ps = _pathset_from_log_rets(log_rets, ["A", "B"])
    val = td.exceedance_correlation(ps, "A", "B", quantile=0.05)
    assert val > 0.5


def test_exceedance_corr_low_for_independent_pair():
    rng = np.random.default_rng(0)
    n_paths, horizon = 4000, 20
    a = rng.normal(0, 0.02, size=(n_paths, horizon, 1))
    b = rng.normal(0, 0.02, size=(n_paths, horizon, 1))
    log_rets = np.concatenate([a, b], axis=2)
    ps = _pathset_from_log_rets(log_rets, ["A", "B"])
    val = td.exceedance_correlation(ps, "A", "B", quantile=0.05)
    assert -0.2 < val < 0.2


def test_exceedance_corr_realized_matches_when_drawn_from_same_dgp():
    rng = np.random.default_rng(0)
    n_obs = 2000
    common = rng.normal(0, 0.02, size=n_obs)
    a = common + rng.normal(0, 0.005, size=n_obs)
    b = common + rng.normal(0, 0.005, size=n_obs)
    realized = pd.DataFrame({"A": np.exp(np.cumsum(a)), "B": np.exp(np.cumsum(b))},
                            index=pd.bdate_range("2018-01-02", periods=n_obs))
    val = td.realized_exceedance_correlation(realized, "A", "B", quantile=0.05)
    assert val > 0.4


def test_exceedance_corr_rejects_unknown_series():
    rng = np.random.default_rng(0)
    log_rets = rng.normal(0, 0.01, size=(100, 5, 2))
    ps = _pathset_from_log_rets(log_rets, ["A", "B"])
    with pytest.raises(KeyError):
        td.exceedance_correlation(ps, "A", "Z", quantile=0.05)
