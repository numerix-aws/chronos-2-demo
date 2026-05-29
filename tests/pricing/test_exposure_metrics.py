import numpy as np
import pandas as pd
import pytest
from chronos2_demo.pricing import exposure as ex
from chronos2_demo.pricing.book import load_book, DEFAULT_BOOK_PATH
from chronos2_demo.types import PathSet


def _pathset_with_known_mtm(mtm: np.ndarray, weights: np.ndarray | None = None):
    """Construct a PathSet where portfolio_mtm would yield `mtm` directly.

    For testing the metrics in isolation we patch out portfolio_mtm; here we
    just need a PathSet with the right shape so the metric functions can be
    invoked with a precomputed MtM tensor.
    """
    n_paths, horizon = mtm.shape
    paths = np.zeros((n_paths, horizon, 1))
    weights = weights if weights is not None else np.full(n_paths, 1.0 / n_paths)
    dates = pd.bdate_range("2022-07-01", periods=horizon)
    return PathSet(paths=paths, weights=weights, series=["x"],
                   dates=dates, source="parametric")


def test_compute_ee_matches_weighted_mean_of_positive_mtm():
    mtm = np.array([[10.0, -5.0],
                    [20.0, 30.0],
                    [-100.0, 40.0]])
    ps = _pathset_with_known_mtm(mtm)
    ee = ex.compute_ee(mtm, ps.weights)
    expected = np.array([(10 + 20) / 3, (0 + 30 + 40) / 3])
    np.testing.assert_allclose(ee, expected)


def test_compute_pfe_at_975_returns_high_quantile():
    rng = np.random.default_rng(0)
    mtm = rng.normal(0, 1, size=(10000, 5))
    ps = _pathset_with_known_mtm(mtm)
    pfe = ex.compute_pfe(mtm, ps.weights, q=0.975)
    # On standard normal, 97.5% quantile of max(z,0) ~ 1.96.
    assert all(1.7 < p < 2.2 for p in pfe)


def test_compute_es_higher_than_pfe():
    rng = np.random.default_rng(0)
    mtm = rng.normal(0, 1, size=(10000, 3))
    ps = _pathset_with_known_mtm(mtm)
    pfe = ex.compute_pfe(mtm, ps.weights, q=0.975)
    es = ex.compute_es(mtm, ps.weights, q=0.975)
    assert all(es[i] > pfe[i] for i in range(3))


def test_compute_metrics_full_pipeline():
    book = load_book(DEFAULT_BOOK_PATH)
    n_paths, horizon = 200, 21
    rng = np.random.default_rng(42)
    series = ["USDEUR", "USDJPY", "USDGBP", "USD_2Y", "USD_5Y", "USD_10Y",
              "EUR_2Y", "EUR_5Y", "EUR_10Y", "JPY_2Y", "JPY_5Y", "JPY_10Y",
              "GBP_2Y", "GBP_5Y", "GBP_10Y"]
    paths = np.zeros((n_paths, horizon, len(series)))
    base = np.array([1.08, 0.0088, 1.35, 0.020, 0.025, 0.030,
                     0.000, 0.005, 0.010, 0.000, 0.000, 0.001,
                     0.010, 0.015, 0.020])
    paths[:] = base
    paths += rng.normal(0, 0.001, size=paths.shape)
    weights = np.full(n_paths, 1.0 / n_paths)
    ps = PathSet(paths=paths, weights=weights, series=series,
                 dates=pd.bdate_range("2022-07-01", periods=horizon),
                 source="parametric")
    metrics = ex.compute_metrics(book, ps)
    assert set(metrics.keys()) == {"ee", "pfe_975", "es_975", "dates"}
    assert metrics["ee"].shape == (horizon,)
    assert metrics["pfe_975"].shape == (horizon,)
    assert metrics["es_975"].shape == (horizon,)
    assert len(metrics["dates"]) == horizon
