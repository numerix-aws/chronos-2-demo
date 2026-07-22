import pandas as pd
import pytest

from chronos2_demo.execution import (
    aligned_run_inputs,
    canonical_json_sha256,
    scenario_role,
)


@pytest.fixture
def panel_and_covariates():
    historical_dates = pd.bdate_range(end="2022-09-30", periods=1260)
    future_dates = pd.bdate_range("2022-10-03", periods=2)
    dates = historical_dates.append(future_dates)
    panel = pd.DataFrame({"USDEUR": range(len(dates))}, index=dates)
    covariates = pd.DataFrame(
        {
            "VIX": range(len(dates)),
            "MOVE": range(len(dates)),
            "WTI": range(len(dates)),
        },
        index=dates,
    )
    return panel, covariates


def test_aligned_run_inputs_uses_exact_lookback_and_no_future_rows(panel_and_covariates):
    panel, covariates = panel_and_covariates

    inputs = aligned_run_inputs(
        panel,
        covariates,
        as_of_date="2022-09-30",
        lookback_days=1260,
    )

    assert len(inputs.panel) == 1260
    assert len(inputs.covariates) == 1260
    assert inputs.panel.index.max().strftime("%Y-%m-%d") == "2022-09-30"
    assert inputs.covariates.index.equals(inputs.panel.index)
    assert inputs.covariates.index.max().strftime("%Y-%m-%d") == "2022-09-30"


def test_aligned_run_inputs_rejects_missing_covariate_rows(panel_and_covariates):
    panel, covariates = panel_and_covariates
    missing = covariates.drop(covariates.index[-10])

    with pytest.raises(ValueError, match="covariates are not aligned"):
        aligned_run_inputs(panel, missing, as_of_date="2022-09-30", lookback_days=1260)


def test_aligned_run_inputs_rejects_missing_covariate_values(panel_and_covariates):
    panel, covariates = panel_and_covariates
    covariates.loc[covariates.index[-10], "VIX"] = None

    with pytest.raises(ValueError, match="covariates are not aligned"):
        aligned_run_inputs(panel, covariates, as_of_date="2022-09-30", lookback_days=1260)


def test_aligned_run_inputs_rejects_missing_panel_values(panel_and_covariates):
    panel, covariates = panel_and_covariates
    panel.loc[panel.index[-10], "USDEUR"] = None

    with pytest.raises(ValueError, match="panel contains missing values"):
        aligned_run_inputs(panel, covariates, as_of_date="2022-09-30", lookback_days=1260)


@pytest.mark.parametrize("lookback_days", [0, -1])
def test_aligned_run_inputs_rejects_nonpositive_lookback(panel_and_covariates, lookback_days):
    panel, covariates = panel_and_covariates

    with pytest.raises(ValueError, match="lookback_days must be positive"):
        aligned_run_inputs(
            panel,
            covariates,
            as_of_date="2022-09-30",
            lookback_days=lookback_days,
        )


def test_aligned_run_inputs_rejects_insufficient_history(panel_and_covariates):
    panel, covariates = panel_and_covariates

    with pytest.raises(ValueError, match="1261 required"):
        aligned_run_inputs(
            panel,
            covariates,
            as_of_date="2022-09-30",
            lookback_days=1261,
        )


@pytest.mark.parametrize("frame_name", ["panel", "covariates"])
def test_aligned_run_inputs_rejects_duplicate_dates(panel_and_covariates, frame_name):
    panel, covariates = panel_and_covariates
    frame = panel if frame_name == "panel" else covariates
    duplicate = pd.concat([frame, frame.iloc[[-1]]])
    if frame_name == "panel":
        panel = duplicate
    else:
        covariates = duplicate

    with pytest.raises(ValueError, match=f"{frame_name} index contains duplicate dates"):
        aligned_run_inputs(panel, covariates, as_of_date="2022-09-30", lookback_days=1260)


@pytest.mark.parametrize("column", ["VIX", "MOVE", "WTI"])
def test_aligned_run_inputs_rejects_missing_required_covariates(panel_and_covariates, column):
    panel, covariates = panel_and_covariates

    with pytest.raises(ValueError, match="missing required covariates"):
        aligned_run_inputs(
            panel,
            covariates.drop(columns=column),
            as_of_date="2022-09-30",
            lookback_days=1260,
        )


def test_canonical_json_sha256_is_order_independent_and_content_sensitive():
    first = {"alpha": 1, "nested": {"beta": 2}}
    reordered = {"nested": {"beta": 2}, "alpha": 1}
    changed = {"alpha": 1, "nested": {"beta": 3}}

    assert canonical_json_sha256(first) == canonical_json_sha256(reordered)
    assert canonical_json_sha256(first) != canonical_json_sha256(changed)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("parametric", "baseline"),
        ("chronos2", "chronos_only"),
        ("chronos2_conditional", "chronos_only"),
        ("blended", "augmented"),
    ],
)
def test_scenario_role_is_derived_from_pathset_source(source, expected):
    assert scenario_role(source) == expected


def test_unknown_pathset_source_is_rejected():
    with pytest.raises(ValueError, match="unsupported PathSet source"):
        scenario_role("first_price_book_call")
