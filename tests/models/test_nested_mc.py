import numpy as np
import pandas as pd
import pytest
from chronos2_demo.types import PathSet
from chronos2_demo.pricing import book as bk, exposure
from chronos2_demo.models import nested_mc


def _pathset(rng, n_paths=40, horizon=6):
    series = ["USDEUR", "USDJPY", "USDGBP", "USD_5Y", "EUR_5Y", "SPX", "NIKKEI225", "US_IG_OAS"]
    dates = pd.bdate_range("2022-07-01", periods=horizon)
    paths = np.abs(rng.normal(1.0, 0.03, size=(n_paths, horizon, len(series)))) + 0.5
    return PathSet(paths=paths, weights=np.full(n_paths, 1/n_paths),
                   series=series, dates=dates, source="parametric")


def test_nested_pfe_matches_closed_form_when_inner_vol_zero(rng):
    ps = _pathset(rng)
    swaps, eq, cds = bk.load_cross_asset_book(bk.DEFAULT_BOOK_PATH)
    nested = nested_mc.nested_pfe(ps, swaps, eq, cds, n_inner=8, inner_vol=0.0, seed=0)
    closed = exposure.compute_pfe(exposure.portfolio_mtm(swaps, ps, eq, cds), ps.weights)
    assert nested.shape == (ps.horizon,)
    np.testing.assert_allclose(nested, closed, rtol=1e-10, atol=1e-6)


def test_nested_run_reports_revaluation_count(rng):
    ps = _pathset(rng, n_paths=10, horizon=4)
    swaps, eq, cds = bk.load_cross_asset_book(bk.DEFAULT_BOOK_PATH)
    result = nested_mc.run_nested(ps, swaps, eq, cds, n_inner=5, inner_vol=0.01, seed=1)
    assert result.pfe.shape == (4,)
    # 10 outer × 4 dates × 5 inner.
    assert result.n_revaluations == 10 * 4 * 5
