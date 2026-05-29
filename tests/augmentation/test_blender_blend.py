import numpy as np
import pandas as pd
from chronos2_demo.augmentation import blender as bl
from chronos2_demo.types import PathSet


def _ps(n_paths, source, fill, horizon=10, n_series=3):
    paths = np.full((n_paths, horizon, n_series), fill, dtype=float)
    weights = np.full(n_paths, 1.0 / n_paths)
    return PathSet(
        paths=paths,
        weights=weights,
        series=["A", "B", "C"],
        dates=pd.bdate_range("2022-07-01", periods=horizon),
        source=source,
    )


def test_blend_paths_concatenates_paths_and_normalizes_weights():
    par = _ps(100, "parametric", fill=1.0)
    chr_ = _ps(80, "chronos2", fill=2.0)
    pnl_par = np.random.default_rng(0).normal(size=100)
    pnl_chr = np.random.default_rng(1).normal(size=80)
    out = bl.blend_paths(par, chr_, pnl_par, pnl_chr, w_stress=0.7)
    assert out.source == "blended"
    assert out.paths.shape == (180, 10, 3)
    # First 100 paths come from parametric (filled with 1.0); next 80 from chronos2 (2.0).
    assert (out.paths[:100] == 1.0).all()
    assert (out.paths[100:] == 2.0).all()
    assert np.isclose(out.weights.sum(), 1.0)


def test_blend_paths_preserves_dates_and_series_from_first_pathset():
    par = _ps(10, "parametric", fill=1.0)
    chr_ = _ps(10, "chronos2", fill=1.0)
    pnl = np.zeros(10)
    out = bl.blend_paths(par, chr_, pnl, pnl, w_stress=0.3)
    assert list(out.series) == par.series
    assert list(out.dates) == list(par.dates)
