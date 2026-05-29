import matplotlib
matplotlib.use("Agg")
import numpy as np
import pandas as pd
import pytest
from chronos2_demo.plotting import path_samples as p
from chronos2_demo.types import PathSet


def _ps(n_paths=200, horizon=21, n_series=2, seed=0):
    rng = np.random.default_rng(seed)
    paths = rng.normal(1.0, 0.05, size=(n_paths, horizon, n_series))
    weights = np.full(n_paths, 1.0 / n_paths)
    return PathSet(paths=paths, weights=weights,
                   series=[f"S{i}" for i in range(n_series)],
                   dates=pd.bdate_range("2022-07-01", periods=horizon),
                   source="parametric")


def test_fan_chart_renders_band_and_thinned_paths():
    ps = _ps(n_paths=200)
    fig = p.plot_path_fan(ps, series="S0", n_path_samples=20, title="x")
    ax = fig.axes[0]
    # 20 sampled paths + 1 line for median (optional) — at least 20 lines.
    assert len(ax.get_lines()) >= 20
    from matplotlib.collections import PolyCollection
    assert any(isinstance(c, PolyCollection) for c in ax.collections)


def test_fan_chart_rejects_unknown_series():
    ps = _ps()
    with pytest.raises(KeyError):
        p.plot_path_fan(ps, series="ZZ", n_path_samples=5, title="x")


def test_fan_chart_caps_n_path_samples_at_n_paths():
    ps = _ps(n_paths=10)
    fig = p.plot_path_fan(ps, series="S0", n_path_samples=100, title="x")
    ax = fig.axes[0]
    # Path lines drawn, regardless: shouldn't exceed n_paths.
    n_path_lines = sum(1 for l in ax.get_lines() if l.get_label() == "_path")
    assert n_path_lines <= 10
