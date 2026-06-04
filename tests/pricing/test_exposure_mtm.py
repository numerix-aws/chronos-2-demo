import numpy as np
import pandas as pd
from chronos2_demo.pricing import exposure as ex
from chronos2_demo.pricing.book import XCCYSwap, load_book, DEFAULT_BOOK_PATH
from chronos2_demo.types import PathSet


def _required_series():
    return ["USDEUR", "USDJPY", "USDGBP", "USD_2Y", "USD_5Y", "USD_10Y",
            "EUR_2Y", "EUR_5Y", "EUR_10Y", "JPY_2Y", "JPY_5Y", "JPY_10Y",
            "GBP_2Y", "GBP_5Y", "GBP_10Y"]


def _flat_pathset(n_paths=50, horizon=63):
    series = _required_series()
    n_s = len(series)
    paths = np.tile(
        np.array([1.08, 0.0088, 1.35, 0.020, 0.025, 0.030,
                  0.000, 0.005, 0.010, 0.000, 0.000, 0.001,
                  0.010, 0.015, 0.020]).reshape(1, 1, n_s),
        (n_paths, horizon, 1),
    )
    weights = np.full(n_paths, 1.0 / n_paths)
    dates = pd.bdate_range("2022-07-01", periods=horizon)
    return PathSet(paths=paths, weights=weights, series=series,
                   dates=dates, source="parametric")


def test_portfolio_mtm_shape_matches_paths():
    book = load_book(DEFAULT_BOOK_PATH)
    ps = _flat_pathset()
    mtm = ex.portfolio_mtm(book, ps)
    assert mtm.shape == (ps.n_paths, ps.horizon)


def test_portfolio_mtm_constant_when_paths_are_constant():
    book = load_book(DEFAULT_BOOK_PATH)
    ps = _flat_pathset()
    mtm = ex.portfolio_mtm(book, ps)
    # All paths should give identical values (time-axis varies via discount theta).
    assert np.allclose(mtm, mtm[0])


def test_portfolio_mtm_responds_to_fx_shock_on_one_path():
    book = load_book(DEFAULT_BOOK_PATH)
    ps = _flat_pathset(n_paths=10)
    paths = ps.paths.copy()
    paths[0, :, ps.series.index("USDEUR")] = 1.30  # EUR strengthens on path 0
    shocked = PathSet(paths=paths, weights=ps.weights, series=ps.series,
                      dates=ps.dates, source="parametric")
    mtm = ex.portfolio_mtm(book, shocked)
    assert not np.isclose(mtm[0, 0], mtm[1, 0])


def test_portfolio_mtm_includes_equity_and_credit(rng):
    import numpy as np, pandas as pd
    from chronos2_demo.types import PathSet
    from chronos2_demo.pricing import book as bk, exposure
    series = ["USDEUR", "USDJPY", "USDGBP", "USD_2Y", "USD_5Y", "USD_10Y",
              "EUR_2Y", "EUR_5Y", "EUR_10Y", "JPY_2Y", "JPY_5Y", "JPY_10Y",
              "GBP_2Y", "GBP_5Y", "GBP_10Y", "SPX", "NIKKEI225", "US_IG_OAS"]
    dates = pd.bdate_range("2022-07-01", periods=10)
    paths = np.abs(rng.normal(1.0, 0.05, size=(20, 10, len(series)))) + 0.5
    ps = PathSet(paths=paths, weights=np.full(20, 1/20), series=series,
                 dates=dates, source="parametric")
    swaps, equities, cds = bk.load_cross_asset_book(bk.DEFAULT_BOOK_PATH)
    mtm = exposure.portfolio_mtm(swaps, ps, equity_forwards=equities, cds_protection=cds)
    assert mtm.shape == (20, 10)
    # Dropping equity+credit changes the MtM (they contribute).
    mtm_swaps_only = exposure.portfolio_mtm(swaps, ps)
    assert not np.allclose(mtm, mtm_swaps_only)
