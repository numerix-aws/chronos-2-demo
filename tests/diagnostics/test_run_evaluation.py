import json

import numpy as np
import pandas as pd
import pytest

from chronos2_demo.diagnostics.run_evaluation import (
    compute_attribution,
    compute_factor_coverage,
    compute_portfolio_coverage,
)
from chronos2_demo.pricing.instruments import EquityForward
from chronos2_demo.types import PathSet


AS_OF_DATE = pd.Timestamp("2022-06-30")


@pytest.fixture
def book():
    equity_forward = EquityForward(
        id="spx-forward",
        index="SPX",
        quote_ccy="USD",
        strike=100.0,
        notional=1.0,
        direction=1,
    )
    return ([], [equity_forward], [])


def _pathset(levels, *, dates=None, series=None, source="parametric"):
    paths = np.asarray(levels, dtype=float)
    dates = dates if dates is not None else pd.bdate_range("2022-07-01", periods=paths.shape[1])
    series = series if series is not None else ["SPX"]
    return PathSet(
        paths=paths,
        weights=np.full(paths.shape[0], 1.0 / paths.shape[0]),
        series=series,
        dates=dates,
        source=source,
    )


@pytest.fixture
def parametric():
    return _pathset(
        [
            [[90.0], [90.0]],
            [[100.0], [100.0]],
            [[110.0], [110.0]],
            [[120.0], [120.0]],
        ]
    )


@pytest.fixture
def chronos():
    return _pathset(
        [
            [[90.0], [90.0]],
            [[95.0], [95.0]],
            [[100.0], [100.0]],
            [[105.0], [105.0]],
        ],
        source="chronos2",
    )


def test_attribution_reports_all_five_distributions(book, parametric, chronos):
    report = compute_attribution(
        book,
        parametric,
        chronos,
        w_stress=0.5305,
        alpha=0.975,
    )

    assert list(report) == [
        "uniform_parametric",
        "uniform_chronos",
        "reweighted_parametric",
        "reweighted_chronos",
        "final_blend",
    ]
    assert report["uniform_parametric"]["scenario_role"] == "baseline"
    assert report["uniform_chronos"]["scenario_role"] == "chronos_only"
    assert report["reweighted_parametric"]["scenario_role"] == "baseline_component"
    assert report["reweighted_chronos"]["scenario_role"] == "chronos_component"
    assert report["final_blend"]["scenario_role"] == "augmented"
    assert report["uniform_parametric"]["delta_pfe_975"] == 0.0


def test_attribution_keeps_negative_chronos_delta_and_source_label(book, parametric, chronos):
    report = compute_attribution(book, parametric, chronos, w_stress=0.5305)

    chronos_result = report["uniform_chronos"]
    assert chronos_result["scenario_role"] == "chronos_only"
    assert chronos_result["delta_pfe_975"] < 0.0
    assert "uplift" not in chronos_result
    json.dumps(report, allow_nan=False)


def _portfolio_distributions(dates):
    return {
        "uniform_parametric": _pathset(
            [[[100.0]] * len(dates), [[110.0]] * len(dates)], dates=dates
        ),
        "uniform_chronos": _pathset(
            [[[100.0]] * len(dates), [[108.0]] * len(dates)],
            dates=dates,
            source="chronos2",
        ),
        "final_blend": _pathset(
            [[[100.0]] * len(dates), [[112.0]] * len(dates)],
            dates=dates,
            source="blended",
        ),
    }


def test_portfolio_coverage_counts_exact_pfe_as_covered_and_reports_breaches(book):
    dates = pd.bdate_range(AS_OF_DATE + pd.offsets.BDay(), periods=3)
    distributions = _portfolio_distributions(dates)
    realized = pd.DataFrame({"SPX": [109.5, 111.5, 106.5]}, index=dates)

    report = compute_portfolio_coverage(book, distributions, realized)

    assert report["available"] is True
    assert list(report["results"]) == [
        "uniform_parametric",
        "uniform_chronos",
        "final_blend",
    ]
    baseline = report["results"]["uniform_parametric"]
    assert baseline["coverage"] == pytest.approx(2.0 / 3.0)
    assert baseline["breach_count"] == 1
    assert baseline["average_breach"] == pytest.approx(2.0)
    assert baseline["maximum_breach"] == pytest.approx(2.0)
    assert report["results"]["uniform_chronos"]["breach_count"] == 2
    assert report["results"]["final_blend"]["breach_count"] == 1
    json.dumps(report, allow_nan=False)


def test_portfolio_coverage_requires_complete_realized_horizon(book):
    dates = pd.bdate_range(AS_OF_DATE + pd.offsets.BDay(), periods=252)
    distributions = _portfolio_distributions(dates)
    realized = pd.DataFrame({"SPX": np.full(17, 100.0)}, index=dates[:17])

    report = compute_portfolio_coverage(book, distributions, realized)

    assert report == {
        "available": False,
        "reason": "realized horizon has 17 of 252 required observations",
    }


def test_portfolio_coverage_requires_exact_forecast_dates_after_as_of(book):
    dates = pd.bdate_range(AS_OF_DATE + pd.offsets.BDay(), periods=3)
    distributions = _portfolio_distributions(dates)
    aligned = pd.DataFrame({"SPX": [100.0, 100.0, 100.0]}, index=dates)
    misaligned = aligned.copy()
    misaligned.index = misaligned.index + pd.offsets.BDay()

    assert dates.min() > AS_OF_DATE
    assert len(aligned) == next(iter(distributions.values())).horizon
    assert compute_portfolio_coverage(book, distributions, aligned)["available"] is True
    assert compute_portfolio_coverage(book, distributions, misaligned) == {
        "available": False,
        "reason": "realized dates do not match the forecast horizon",
    }


@pytest.mark.parametrize(
    ("mismatch", "reason"),
    [
        (
            "horizon",
            "model distribution 'uniform_chronos' horizon does not match the other distributions",
        ),
        (
            "dates",
            "model distribution 'uniform_chronos' dates do not match the other distributions",
        ),
        (
            "series",
            "model distribution 'uniform_chronos' series do not match the other distributions",
        ),
    ],
)
def test_portfolio_coverage_rejects_nonfirst_distribution_misalignment(
    book, mismatch, reason
):
    dates = pd.bdate_range(AS_OF_DATE + pd.offsets.BDay(), periods=3)
    distributions = _portfolio_distributions(dates)
    if mismatch == "horizon":
        distributions["uniform_chronos"] = _pathset(
            [[[100.0]] * 2, [[108.0]] * 2],
            dates=dates[:2],
            source="chronos2",
        )
    elif mismatch == "dates":
        distributions["uniform_chronos"] = _pathset(
            [[[100.0]] * 3, [[108.0]] * 3],
            dates=dates + pd.offsets.BDay(),
            source="chronos2",
        )
    else:
        distributions["uniform_chronos"] = _pathset(
            [[[100.0]] * 3, [[108.0]] * 3],
            dates=dates,
            series=["OTHER"],
            source="chronos2",
        )
    realized = pd.DataFrame({"SPX": [100.0, 100.0, 100.0]}, index=dates)

    report = compute_portfolio_coverage(book, distributions, realized)

    assert report == {"available": False, "reason": reason}
    json.dumps(report, allow_nan=False)


def _factor_distributions(dates):
    paths = np.array(
        [
            [[0.0, 0.0]] * len(dates),
            [[0.0, 0.0]] * len(dates),
            [[10.0, 10.0]] * len(dates),
            [[10.0, 10.0]] * len(dates),
        ]
    )
    return {
        "uniform_parametric": _pathset(paths, dates=dates, series=["S1", "S2"]),
        "uniform_chronos": _pathset(
            paths, dates=dates, series=["S1", "S2"], source="chronos2"
        ),
        "final_blend": _pathset(
            paths, dates=dates, series=["S1", "S2"], source="blended"
        ),
    }


def test_factor_coverage_reports_central_95_percent_by_series_and_regime():
    dates = pd.bdate_range(AS_OF_DATE + pd.offsets.BDay(), periods=4)
    distributions = _factor_distributions(dates)
    realized = pd.DataFrame(
        {"S1": [5.0, 15.0, 5.0, 15.0], "S2": [5.0, 5.0, 15.0, 15.0]},
        index=dates,
    )
    regimes = pd.DataFrame({"w_stress": [0.2, 0.8, 0.2, 0.8]}, index=dates)

    report = compute_factor_coverage(
        distributions,
        realized,
        regimes,
        regime_threshold=0.7,
    )

    assert report["available"] is True
    assert list(report["results"]) == [
        "uniform_parametric",
        "uniform_chronos",
        "final_blend",
    ]
    baseline = report["results"]["uniform_parametric"]
    assert baseline["nominal"] == 0.95
    assert baseline["coverage"] == 0.5
    assert baseline["per_series"] == {"S1": 0.5, "S2": 0.5}
    assert baseline["calm"] == {"S1": 1.0, "S2": 0.5}
    assert baseline["stress"] == {"S1": 0.0, "S2": 0.5}
    json.dumps(report, allow_nan=False)


def test_factor_coverage_uses_null_for_an_empty_regime():
    dates = pd.bdate_range(AS_OF_DATE + pd.offsets.BDay(), periods=2)
    distributions = _factor_distributions(dates)
    realized = pd.DataFrame({"S1": [5.0, 5.0], "S2": [5.0, 5.0]}, index=dates)
    regimes = pd.DataFrame({"w_stress": [0.9, 0.9]}, index=dates)

    report = compute_factor_coverage(
        distributions,
        realized,
        regimes,
        regime_threshold=0.7,
    )

    assert report["results"]["uniform_parametric"]["calm"] == {
        "S1": None,
        "S2": None,
    }
    json.dumps(report, allow_nan=False)


def test_factor_coverage_rejects_misaligned_regimes():
    dates = pd.bdate_range(AS_OF_DATE + pd.offsets.BDay(), periods=2)
    distributions = _factor_distributions(dates)
    realized = pd.DataFrame({"S1": [5.0, 5.0], "S2": [5.0, 5.0]}, index=dates)
    regimes = pd.DataFrame(
        {"w_stress": [0.2, 0.8]}, index=dates + pd.offsets.BDay()
    )

    report = compute_factor_coverage(
        distributions,
        realized,
        regimes,
        regime_threshold=0.7,
    )

    assert report == {
        "available": False,
        "reason": "realized regimes do not match the forecast horizon",
    }


def test_factor_coverage_rejects_nonfirst_distribution_misalignment():
    dates = pd.bdate_range(AS_OF_DATE + pd.offsets.BDay(), periods=2)
    distributions = _factor_distributions(dates)
    nonfirst = distributions["uniform_chronos"]
    distributions["uniform_chronos"] = _pathset(
        nonfirst.paths,
        dates=dates + pd.offsets.BDay(),
        series=nonfirst.series,
        source="chronos2",
    )
    realized = pd.DataFrame({"S1": [5.0, 5.0], "S2": [5.0, 5.0]}, index=dates)
    regimes = pd.DataFrame({"w_stress": [0.2, 0.8]}, index=dates)

    report = compute_factor_coverage(
        distributions,
        realized,
        regimes,
        regime_threshold=0.7,
    )

    assert report == {
        "available": False,
        "reason": "model distribution 'uniform_chronos' dates do not match the other distributions",
    }
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("invalid_weight", [np.nan, np.inf, -np.inf])
def test_factor_coverage_rejects_nonfinite_regime_weights(invalid_weight):
    dates = pd.bdate_range(AS_OF_DATE + pd.offsets.BDay(), periods=2)
    distributions = _factor_distributions(dates)
    realized = pd.DataFrame({"S1": [5.0, 5.0], "S2": [5.0, 5.0]}, index=dates)
    regimes = pd.DataFrame({"w_stress": [0.2, invalid_weight]}, index=dates)

    report = compute_factor_coverage(
        distributions,
        realized,
        regimes,
        regime_threshold=0.7,
    )

    assert report == {
        "available": False,
        "reason": "realized regimes contain missing or non-finite w_stress values",
    }
    json.dumps(report, allow_nan=False)
