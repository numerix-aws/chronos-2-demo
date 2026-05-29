import numpy as np
import pandas as pd
import pytest
from chronos2_demo.models import baseline_mc
from chronos2_demo.types import PathSet


def _panel(n=600, k=4, seed=0):
    rng = np.random.default_rng(seed)
    raw = rng.normal(0, 0.005, size=(n, k)).cumsum(axis=0) + 1.0
    return pd.DataFrame(raw, columns=list("ABCD"),
                        index=pd.bdate_range("2020-01-02", periods=n))


def test_simulate_baseline_returns_pathset_with_correct_shape():
    panel = _panel()
    ps = baseline_mc.simulate_baseline(
        panel, as_of="2022-01-03", horizon=63, n_paths=500, n_components=3, seed=0
    )
    assert isinstance(ps, PathSet)
    assert ps.source == "parametric"
    assert ps.paths.shape == (500, 63, 4)
    assert ps.series == ["A", "B", "C", "D"]
    assert np.isclose(ps.weights.sum(), 1.0)


def test_simulate_baseline_paths_start_near_as_of_levels():
    panel = _panel()
    as_of = "2022-01-03"
    ps = baseline_mc.simulate_baseline(
        panel, as_of=as_of, horizon=10, n_paths=200, n_components=3, seed=0
    )
    levels_at_as_of = panel.loc[as_of].values  # (4,)
    first_step = ps.paths[:, 0, :].mean(axis=0)
    rel_err = np.abs(first_step - levels_at_as_of) / np.abs(levels_at_as_of)
    assert (rel_err < 0.05).all()


def test_simulate_baseline_is_deterministic_under_same_seed():
    panel = _panel()
    a = baseline_mc.simulate_baseline(panel, "2022-01-03", 30, 100, 3, seed=42)
    b = baseline_mc.simulate_baseline(panel, "2022-01-03", 30, 100, 3, seed=42)
    np.testing.assert_array_equal(a.paths, b.paths)
