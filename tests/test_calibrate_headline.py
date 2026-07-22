import ast
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from chronos2_demo.run_spec import canonical_run_payload, compile_run_spec
from scripts import calibrate_headline


PROVENANCE = {
    "market_snapshot_id": "market-v1",
    "market_sha256": "a" * 64,
    "covariate_snapshot_id": "cov-v1",
    "covariate_sha256": "b" * 64,
    "chronos_endpoint": "chronos2-demo",
    "chronos_model_version": "chronos-2",
    "baseline_image_digest": "sha256:baseline",
    "chronos_image_digest": "sha256:chronos",
    "agent_image_digest": "sha256:agent",
    "book_version": "cross_asset_demo_v1",
    "blend_version": "importance_weight_v1",
    "pricing_version": "cross_asset_v1",
    "tool_bundle_version": "git:test",
    "strands_version": "1.30.0",
}
PROFILE_PROMPT = "Run the stage-safe headline demo."


def _market_frames(future_periods=17):
    history = pd.bdate_range(end="2022-09-30", periods=1260)
    future = pd.bdate_range("2022-10-03", periods=future_periods)
    dates = history.append(future)
    panel = pd.DataFrame(
        {
            "USDEUR": np.linspace(1.0, 2.0, len(dates)),
            "SPX": np.linspace(3000.0, 4000.0, len(dates)),
        },
        index=dates,
    )
    covariates = pd.DataFrame(
        {
            "VIX": np.linspace(15.0, 25.0, len(dates)),
            "MOVE": np.linspace(80.0, 120.0, len(dates)),
            "WTI": np.linspace(50.0, 90.0, len(dates)),
        },
        index=dates,
    )
    return panel, covariates


@pytest.fixture
def market_data():
    return _market_frames()


def _parquet_bytes(frame):
    buffer = io.BytesIO()
    frame.to_parquet(buffer)
    return buffer.getvalue()


def _install_calculation_mocks(monkeypatch, forecast_dates=None):
    if forecast_dates is None:
        forecast_dates = pd.bdate_range("2022-10-03", periods=252)
    parametric = SimpleNamespace(dates=forecast_dates, horizon=len(forecast_dates))
    chronos = SimpleNamespace(dates=forecast_dates, horizon=len(forecast_dates))
    augmented = SimpleNamespace(dates=forecast_dates, horizon=len(forecast_dates))
    book = ([object()], [object()], [object()])
    endpoint = object()

    baseline_calls = []
    chronos_calls = []
    book_paths = []
    mtm_calls = []
    mtm_outputs = []
    blend_calls = []
    metrics_calls = []

    def baseline_stub(panel, **kwargs):
        baseline_calls.append((panel, kwargs))
        return parametric

    def chronos_stub(client, **kwargs):
        chronos_calls.append((client, kwargs))
        return chronos

    monkeypatch.setattr(calibrate_headline.baseline_mc, "simulate_baseline", baseline_stub)
    monkeypatch.setattr(calibrate_headline.chronos2_client, "simulate_chronos2", chronos_stub)
    def load_book_stub(path):
        book_paths.append(path)
        return book

    def mtm_stub(*args, **kwargs):
        mtm_calls.append((args, kwargs))
        result = np.full((500, 1), len(mtm_calls), dtype=float)
        mtm_outputs.append(result)
        return result

    def blend_stub(*args, **kwargs):
        blend_calls.append((args, kwargs))
        return augmented

    monkeypatch.setattr(calibrate_headline.bk, "load_cross_asset_book", load_book_stub)
    monkeypatch.setattr(
        calibrate_headline.exposure,
        "portfolio_mtm",
        mtm_stub,
    )
    monkeypatch.setattr(
        calibrate_headline.blender,
        "blend_paths",
        blend_stub,
    )
    metrics = iter(
        {
            "dates": forecast_dates,
            "ee": np.array([value]),
            "pfe_975": np.array([value + 1.0]),
            "es_975": np.array([value + 2.0]),
        }
        for value in (10.0, 20.0, 30.0)
    )
    def metrics_stub(*args, **kwargs):
        metrics_calls.append((args, kwargs))
        return next(metrics)

    monkeypatch.setattr(calibrate_headline.exposure, "compute_metrics", metrics_stub)
    monkeypatch.setattr(
        calibrate_headline.data_regimes,
        "w_stress_series",
        lambda panel: pd.Series(0.2, index=panel.index, name="w_stress"),
    )
    monkeypatch.setattr(
        calibrate_headline.data_regimes,
        "label_regimes",
        lambda panel, threshold: pd.Series("calm", index=panel.index, name="regime"),
    )

    diagnostics_calls = {}

    def attribution_stub(*args, **kwargs):
        diagnostics_calls["attribution"] = (args, kwargs)
        return {"distribution_count": 5}

    def portfolio_stub(*args, **kwargs):
        diagnostics_calls["portfolio_coverage"] = (args, kwargs)
        return {"available": False, "reason": "incomplete held-out horizon"}

    def factor_stub(*args, **kwargs):
        diagnostics_calls["factor_coverage"] = (args, kwargs)
        return {"available": False, "reason": "incomplete held-out horizon"}

    monkeypatch.setattr(calibrate_headline, "compute_attribution", attribution_stub)
    monkeypatch.setattr(calibrate_headline, "compute_portfolio_coverage", portfolio_stub)
    monkeypatch.setattr(calibrate_headline, "compute_factor_coverage", factor_stub)
    return SimpleNamespace(
        endpoint=endpoint,
        parametric=parametric,
        chronos=chronos,
        augmented=augmented,
        book=book,
        baseline_calls=baseline_calls,
        chronos_calls=chronos_calls,
        book_paths=book_paths,
        mtm_calls=mtm_calls,
        mtm_outputs=mtm_outputs,
        blend_calls=blend_calls,
        metrics_calls=metrics_calls,
        diagnostics_calls=diagnostics_calls,
    )


def _write_cli_inputs(tmp_path, panel, covariates, provenance=PROVENANCE):
    panel_raw = _parquet_bytes(panel)
    covariates_raw = _parquet_bytes(covariates)
    (tmp_path / "panel.parquet").write_bytes(panel_raw)
    (tmp_path / "covariates.parquet").write_bytes(covariates_raw)
    bound = {
        **provenance,
        "market_sha256": hashlib.sha256(panel_raw).hexdigest(),
        "covariate_sha256": hashlib.sha256(covariates_raw).hexdigest(),
    }
    provenance_path = tmp_path / "deployment-provenance.json"
    provenance_path.write_text(json.dumps(bound))
    return bound, provenance_path


def test_run_calibration_uses_shared_spec_inputs_engines_book_and_diagnostics(
    monkeypatch, market_data
):
    panel, covariates = market_data
    observed = _install_calculation_mocks(monkeypatch)

    result = calibrate_headline.run_calibration(
        prompt=PROFILE_PROMPT,
        provenance=PROVENANCE,
        panel=panel,
        covariates=covariates,
        endpoint=observed.endpoint,
        execution_id="calibration-run-1",
    )

    spec = compile_run_spec(
        PROFILE_PROMPT,
        provenance=PROVENANCE,
        execution_id="calibration-run-1",
    )
    expected_run_spec = {
        **canonical_run_payload(spec),
        "execution_id": spec.execution_id,
        "spec_hash": spec.spec_hash,
    }
    assert result["run_spec"] == expected_run_spec
    assert result["inputs"] == {"panel_rows": 1260, "covariate_rows": 1260}
    assert result["terminal_metrics"] == {
        "baseline": {
            "date": "2023-09-19",
            "ee": 10.0,
            "pfe_975": 11.0,
            "es_975": 12.0,
        },
        "chronos_only": {
            "date": "2023-09-19",
            "ee": 20.0,
            "pfe_975": 21.0,
            "es_975": 22.0,
        },
        "augmented": {
            "date": "2023-09-19",
            "ee": 30.0,
            "pfe_975": 31.0,
            "es_975": 32.0,
        },
    }
    json.dumps(result, allow_nan=False)

    baseline_panel, baseline_kwargs = observed.baseline_calls[0]
    chronos_client, chronos_kwargs = observed.chronos_calls[0]
    assert len(baseline_panel) == 1260
    assert baseline_panel.index.equals(chronos_kwargs["panel"].index)
    assert baseline_panel.equals(chronos_kwargs["panel"])
    assert chronos_kwargs["covariates"].index.equals(baseline_panel.index)
    assert len(chronos_kwargs["covariates"]) == 1260
    assert baseline_kwargs == {
        "as_of": "2022-09-30",
        "horizon": 252,
        "n_paths": 500,
        "n_components": 5,
        "seed": 0,
    }
    assert chronos_client.endpoint is observed.endpoint
    assert chronos_kwargs == {
        "panel": baseline_panel,
        "as_of": "2022-09-30",
        "horizon": 252,
        "n_paths": 500,
        "lookback_days": 1260,
        "covariates": chronos_kwargs["covariates"],
        "conditioning": None,
        "seed": 0,
    }
    assert observed.book_paths == [calibrate_headline.bk.DEFAULT_BOOK_PATH]
    swaps, equity_forwards, cds_protection = observed.book
    assert observed.mtm_calls == [
        (
            (swaps, observed.parametric),
            {
                "equity_forwards": equity_forwards,
                "cds_protection": cds_protection,
            },
        ),
        (
            (swaps, observed.chronos),
            {
                "equity_forwards": equity_forwards,
                "cds_protection": cds_protection,
            },
        ),
    ]
    assert len(observed.blend_calls) == 1
    blend_args, blend_kwargs = observed.blend_calls[0]
    assert blend_args[0] is observed.parametric
    assert blend_args[1] is observed.chronos
    assert np.array_equal(blend_args[2], observed.mtm_outputs[0][:, -1])
    assert np.array_equal(blend_args[3], observed.mtm_outputs[1][:, -1])
    assert blend_kwargs == {"w_stress": 0.5305}
    assert [args for args, _ in observed.metrics_calls] == [
        (swaps, observed.parametric),
        (swaps, observed.chronos),
        (swaps, observed.augmented),
    ]
    assert all(
        kwargs
        == {
            "q": 0.975,
            "equity_forwards": equity_forwards,
            "cds_protection": cds_protection,
        }
        for _, kwargs in observed.metrics_calls
    )

    attribution_args, attribution_kwargs = observed.diagnostics_calls["attribution"]
    assert attribution_args == (observed.book, observed.parametric, observed.chronos)
    assert attribution_kwargs == {"w_stress": 0.5305}
    for name in ("portfolio_coverage", "factor_coverage"):
        future_panel = observed.diagnostics_calls[name][0][-1 if name == "portfolio_coverage" else -2]
        assert len(future_panel) == 17
        assert (future_panel.index > pd.Timestamp("2022-09-30")).all()
    assert result["diagnostics"]["portfolio_coverage"]["available"] is False
    assert result["diagnostics"]["factor_coverage"]["available"] is False


def test_clarification_fails_before_engines(monkeypatch, market_data):
    panel, covariates = market_data
    monkeypatch.setattr(
        calibrate_headline.baseline_mc,
        "simulate_baseline",
        lambda *args, **kwargs: pytest.fail("baseline engine must not run"),
    )
    monkeypatch.setattr(
        calibrate_headline.chronos2_client,
        "simulate_chronos2",
        lambda *args, **kwargs: pytest.fail("Chronos engine must not run"),
    )

    with pytest.raises(ValueError, match="Please specify"):
        calibrate_headline.run_calibration(
            prompt="Run exposure.",
            provenance=PROVENANCE,
            panel=panel,
            covariates=covariates,
            endpoint=object(),
            execution_id="clarification-run",
        )


def test_required_provenance_schema_matches_run_spec_contract():
    assert calibrate_headline.REQUIRED_PROVENANCE_KEYS == frozenset(PROVENANCE)


@pytest.mark.parametrize(
    "invalid_provenance",
    [
        {key: value for key, value in PROVENANCE.items() if key != "market_sha256"},
        {**PROVENANCE, "chronos_model_version": ""},
        {**PROVENANCE, "pricing_version": "   "},
        {**PROVENANCE, "strands_version": 1},
    ],
)
def test_run_calibration_rejects_incomplete_or_empty_provenance_before_engines(
    monkeypatch, market_data, invalid_provenance
):
    panel, covariates = market_data
    observed = _install_calculation_mocks(monkeypatch)

    with pytest.raises(ValueError, match="deployment provenance"):
        calibrate_headline.run_calibration(
            prompt=PROFILE_PROMPT,
            provenance=invalid_provenance,
            panel=panel,
            covariates=covariates,
            endpoint=observed.endpoint,
            execution_id="invalid-provenance",
        )

    assert observed.baseline_calls == []
    assert observed.chronos_calls == []
    assert observed.book_paths == []


def test_run_calibration_rejects_book_identity_before_engines(monkeypatch, market_data):
    panel, covariates = market_data
    observed = _install_calculation_mocks(monkeypatch)
    mismatched = {**PROVENANCE, "book_version": "cross_asset_demo_v2"}

    with pytest.raises(ValueError, match="book identity"):
        calibrate_headline.run_calibration(
            prompt=PROFILE_PROMPT,
            provenance=mismatched,
            panel=panel,
            covariates=covariates,
            endpoint=observed.endpoint,
            execution_id="book-mismatch",
        )

    assert observed.baseline_calls == []
    assert observed.chronos_calls == []
    assert observed.book_paths == []


def test_cli_requires_explicit_provenance_and_writes_strict_sorted_json(
    monkeypatch, tmp_path, market_data
):
    panel, covariates = market_data
    bound_provenance, provenance_path = _write_cli_inputs(
        tmp_path, panel, covariates
    )
    output_path = tmp_path / "calibration.json"
    endpoint = object()
    artifact = {"run_spec": {"execution_id": "calibration-run-1"}, "value": 1.0}

    monkeypatch.setattr(calibrate_headline, "OUT", output_path)
    monkeypatch.setattr(calibrate_headline.config, "DATA_CURATED", tmp_path)
    events = []
    load_verified_parquet = calibrate_headline._load_verified_parquet

    def load_stub(path, *, expected_hash, label):
        events.append(f"verify:{label}")
        return load_verified_parquet(
            path, expected_hash=expected_hash, label=label
        )

    def endpoint_stub(name):
        events.append("open:endpoint")
        return endpoint

    monkeypatch.setattr(calibrate_headline, "_load_verified_parquet", load_stub)
    monkeypatch.setattr(
        calibrate_headline.sagemaker_endpoint, "open_endpoint", endpoint_stub
    )
    observed = {}

    def run_stub(**kwargs):
        events.append("run:calibration")
        observed.update(kwargs)
        return artifact

    monkeypatch.setattr(calibrate_headline, "run_calibration", run_stub)

    assert calibrate_headline.main(
        [
            "--profile",
            "stage_safe_headline_v1",
            "--execution-id",
            "calibration-run-1",
            "--provenance-file",
            str(provenance_path),
        ]
    ) == 0

    assert observed["prompt"] == PROFILE_PROMPT
    assert observed["provenance"] == bound_provenance
    assert observed["panel"].equals(panel)
    assert observed["covariates"].equals(covariates)
    assert observed["endpoint"] is endpoint
    assert observed["execution_id"] == "calibration-run-1"
    assert events == [
        "verify:market",
        "verify:covariate",
        "open:endpoint",
        "run:calibration",
    ]
    assert output_path.read_text() == json.dumps(
        artifact, allow_nan=False, indent=2, sort_keys=True
    ) + "\n"

    monkeypatch.setattr(calibrate_headline, "run_calibration", lambda **kwargs: {"value": float("nan")})
    with pytest.raises(ValueError, match="Out of range float values"):
        calibrate_headline.main(
            [
                "--prompt",
                PROFILE_PROMPT,
                "--provenance-file",
                str(provenance_path),
            ]
        )


def test_cli_rejects_incomplete_provenance_before_opening_endpoint(
    monkeypatch, tmp_path, market_data
):
    panel, covariates = market_data
    _, provenance_path = _write_cli_inputs(tmp_path, panel, covariates)
    incomplete = dict(PROVENANCE)
    incomplete.pop("market_snapshot_id")
    provenance_path.write_text(json.dumps(incomplete))
    monkeypatch.setattr(calibrate_headline.config, "DATA_CURATED", tmp_path)
    monkeypatch.setattr(
        calibrate_headline.sagemaker_endpoint,
        "open_endpoint",
        lambda name: pytest.fail("endpoint must not be opened"),
    )

    with pytest.raises(ValueError, match="deployment provenance"):
        calibrate_headline.main([
            "--profile",
            "stage_safe_headline_v1",
            "--provenance-file",
            str(provenance_path),
        ])


@pytest.mark.parametrize(
    ("filename", "hash_key", "label"),
    [
        ("panel.parquet", "market_sha256", "market"),
        ("covariates.parquet", "covariate_sha256", "covariate"),
    ],
)
def test_cli_rejects_tampered_snapshot_bytes_before_endpoint_or_engines(
    monkeypatch, tmp_path, market_data, filename, hash_key, label
):
    panel, covariates = market_data
    provenance, provenance_path = _write_cli_inputs(tmp_path, panel, covariates)
    snapshot_path = tmp_path / filename
    snapshot_path.write_bytes(snapshot_path.read_bytes() + b"tampered")
    assert hashlib.sha256(snapshot_path.read_bytes()).hexdigest() != provenance[hash_key]
    monkeypatch.setattr(calibrate_headline.config, "DATA_CURATED", tmp_path)
    monkeypatch.setattr(
        calibrate_headline.sagemaker_endpoint,
        "open_endpoint",
        lambda name: pytest.fail("endpoint must not be opened"),
    )
    monkeypatch.setattr(
        calibrate_headline,
        "run_calibration",
        lambda **kwargs: pytest.fail("engines must not run"),
    )

    with pytest.raises(ValueError, match=f"{label} snapshot content hash mismatch"):
        calibrate_headline.main([
            "--profile",
            "stage_safe_headline_v1",
            "--provenance-file",
            str(provenance_path),
        ])


def test_held_out_panel_normalizes_noon_as_of_sorts_and_matches_forecast_dates(
    monkeypatch,
):
    panel, covariates = _market_frames(future_periods=252)
    as_of_position = panel.index.get_loc(pd.Timestamp("2022-09-30"))
    panel_index = panel.index.to_list()
    panel_index[as_of_position] = pd.Timestamp("2022-09-30 12:00")
    panel.index = pd.DatetimeIndex(panel_index)
    panel = panel.iloc[::-1]
    covariates = covariates.iloc[::-1]
    forecast_dates = pd.bdate_range("2022-10-03", periods=252)
    observed = _install_calculation_mocks(monkeypatch, forecast_dates=forecast_dates)

    calibrate_headline.run_calibration(
        prompt=PROFILE_PROMPT,
        provenance=PROVENANCE,
        panel=panel,
        covariates=covariates,
        endpoint=observed.endpoint,
        execution_id="normalized-held-out",
    )

    portfolio_future = observed.diagnostics_calls["portfolio_coverage"][0][2]
    factor_future = observed.diagnostics_calls["factor_coverage"][0][1]
    assert portfolio_future.index.equals(forecast_dates)
    assert factor_future.index.equals(forecast_dates)
    assert portfolio_future.index.is_monotonic_increasing
    assert (portfolio_future.index > pd.Timestamp("2022-09-30")).all()


def test_held_out_panel_rejects_duplicate_normalized_dates_before_engines(
    monkeypatch, market_data
):
    panel, covariates = market_data
    duplicate = panel.loc[[pd.Timestamp("2022-10-03")]].copy()
    duplicate.index = pd.DatetimeIndex([pd.Timestamp("2022-10-03 12:00")])
    panel = pd.concat([panel, duplicate])
    observed = _install_calculation_mocks(monkeypatch)

    with pytest.raises(ValueError, match="market snapshot index contains duplicate dates"):
        calibrate_headline.run_calibration(
            prompt=PROFILE_PROMPT,
            provenance=PROVENANCE,
            panel=panel,
            covariates=covariates,
            endpoint=observed.endpoint,
            execution_id="duplicate-held-out",
        )

    assert observed.baseline_calls == []
    assert observed.chronos_calls == []


def test_complete_held_out_dates_must_match_every_distribution_before_coverage(
    monkeypatch,
):
    panel, covariates = _market_frames(future_periods=252)
    forecast_dates = pd.bdate_range("2022-10-03", periods=252)
    observed = _install_calculation_mocks(monkeypatch, forecast_dates=forecast_dates)
    observed.chronos.dates = forecast_dates + pd.offsets.BDay()

    with pytest.raises(ValueError, match="chronos_only forecast dates"):
        calibrate_headline.run_calibration(
            prompt=PROFILE_PROMPT,
            provenance=PROVENANCE,
            panel=panel,
            covariates=covariates,
            endpoint=observed.endpoint,
            execution_id="mismatched-held-out",
        )

    assert observed.diagnostics_calls == {}


def _is_spec_field(node, field):
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "spec"
        and node.attr == field
    )


def _source_guard_violations(source):
    tree = ast.parse(source)
    direct_keywords = {
        "lookback_days": "lookback_days",
        "horizon": "horizon",
        "n_paths": "n_paths",
        "w_stress": "w_stress",
        "baseline_components": "baseline_components",
        "baseline_seed": "baseline_seed",
        "chronos_seed": "chronos_seed",
        "regime_threshold": "regime_threshold",
    }
    call_keywords = {
        ("simulate_baseline", "n_components"): "baseline_components",
        ("simulate_baseline", "seed"): "baseline_seed",
        ("simulate_chronos2", "seed"): "chronos_seed",
        ("label_regimes", "threshold"): "regime_threshold",
    }
    guarded_names = set(direct_keywords) | {"n_components"}
    violations = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            for target in targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id in guarded_names
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, (int, float))
                ):
                    violations.append((target.id, value.value, node.lineno))
        if isinstance(node, ast.Call):
            function_name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else node.func.id if isinstance(node.func, ast.Name) else None
            )
            for keyword in node.keywords:
                expected = call_keywords.get((function_name, keyword.arg))
                expected = expected or direct_keywords.get(keyword.arg)
                if expected and not _is_spec_field(keyword.value, expected):
                    violations.append(
                        (keyword.arg, ast.unparse(keyword.value), keyword.lineno)
                    )
            if function_name == "add_argument" and node.args:
                option = node.args[0]
                if isinstance(option, ast.Constant) and option.value in {
                    "--lookback-days",
                    "--horizon",
                    "--n-paths",
                    "--w-stress",
                    "--baseline-components",
                    "--n-components",
                    "--baseline-seed",
                    "--chronos-seed",
                    "--regime-threshold",
                }:
                    defaults = [kw for kw in node.keywords if kw.arg == "default"]
                    if defaults:
                        violations.append((option.value, "CLI default", node.lineno))
    return violations


def test_source_has_no_independent_quantitative_defaults():
    source = Path(calibrate_headline.__file__).read_text()
    violations = _source_guard_violations(source)

    assert violations == []


@pytest.mark.parametrize(
    ("run_spec_access", "literal", "guarded_name"),
    [
        ("n_components=spec.baseline_components", "n_components=5", "n_components"),
        ("seed=spec.baseline_seed", "seed=0", "seed"),
        ("seed=spec.chronos_seed", "seed=0", "seed"),
        (
            "threshold=spec.regime_threshold",
            "threshold=0.7",
            "threshold",
        ),
        (
            "regime_threshold=spec.regime_threshold",
            "regime_threshold=0.7",
            "regime_threshold",
        ),
    ],
)
def test_source_guard_rejects_run_spec_numeric_mutations(
    run_spec_access, literal, guarded_name
):
    source = Path(calibrate_headline.__file__).read_text()
    mutated = source.replace(run_spec_access, literal, 1)
    assert mutated != source

    violations = _source_guard_violations(mutated)

    assert any(name == guarded_name for name, _, _ in violations)
    assert all(name != "q" for name, _, _ in violations)
