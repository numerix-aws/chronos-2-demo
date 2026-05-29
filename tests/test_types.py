import numpy as np
import pandas as pd
import pytest
from chronos2_demo.types import PathSet


def test_pathset_construction_and_shape():
    paths = np.zeros((1000, 252, 5))
    weights = np.ones(1000) / 1000
    series_names = ["USDEUR", "USDJPY", "USD_2Y", "USD_5Y", "USD_10Y"]
    dates = pd.bdate_range("2022-07-01", periods=252)
    ps = PathSet(paths=paths, weights=weights, series=series_names, dates=dates,
                 source="parametric")
    assert ps.n_paths == 1000
    assert ps.horizon == 252
    assert ps.n_series == 5
    assert ps.source == "parametric"


def test_pathset_weights_must_be_positive_and_sum_to_one():
    paths = np.zeros((10, 5, 3))
    series_names = ["A", "B", "C"]
    dates = pd.bdate_range("2022-07-01", periods=5)
    with pytest.raises(ValueError, match="non-negative"):
        PathSet(paths=paths, weights=np.array([1.0]*9 + [-0.1]),
                series=series_names, dates=dates, source="x")
    with pytest.raises(ValueError, match="sum to 1"):
        PathSet(paths=paths, weights=np.full(10, 0.05),
                series=series_names, dates=dates, source="x")


def test_pathset_rejects_shape_mismatch():
    with pytest.raises(ValueError, match="shape"):
        PathSet(paths=np.zeros((10, 5, 3)), weights=np.ones(10)/10,
                series=["A", "B"], dates=pd.bdate_range("2022-07-01", periods=5),
                source="x")
