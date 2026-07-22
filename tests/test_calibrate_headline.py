import ast
import json
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


@pytest.fixture
def market_data():
    history = pd.bdate_range(end="2022-09-30", periods=1260)
    future = pd.bdate_range("2022-10-03", periods=17)
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


def _install_calculation_mocks(monkeypatch):
    parametric = object()
    chronos = object()
    augmented = object()
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
    terminal_dates = pd.bdate_range("2022-10-03", periods=252)
    metrics = iter(
        {
            "dates": terminal_dates,
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


def test_cli_requires_explicit_provenance_and_writes_strict_sorted_json(
    monkeypatch, tmp_path, market_data
):
    panel, covariates = market_data
    provenance_path = tmp_path / "deployment-provenance.json"
    provenance_path.write_text(json.dumps(PROVENANCE))
    output_path = tmp_path / "calibration.json"
    endpoint = object()
    artifact = {"run_spec": {"execution_id": "calibration-run-1"}, "value": 1.0}

    monkeypatch.setattr(calibrate_headline, "OUT", output_path)
    monkeypatch.setattr(calibrate_headline.pd, "read_parquet", lambda path: panel if "panel" in str(path) else covariates)
    monkeypatch.setattr(calibrate_headline.sagemaker_endpoint, "open_endpoint", lambda name: endpoint)
    observed = {}

    def run_stub(**kwargs):
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
    assert observed["provenance"] == PROVENANCE
    assert observed["endpoint"] is endpoint
    assert observed["execution_id"] == "calibration-run-1"
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


def test_source_has_no_independent_quantitative_defaults():
    source = calibrate_headline.__file__
    tree = ast.parse(open(source, encoding="utf-8").read(), filename=source)
    guarded_names = {"lookback_days", "horizon", "n_paths", "w_stress"}
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
        if isinstance(node, ast.keyword) and node.arg in guarded_names:
            from_spec = (
                isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "spec"
                and node.value.attr == node.arg
            )
            if not from_spec:
                violations.append((node.arg, ast.unparse(node.value), node.lineno))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "add_argument" and node.args:
                option = node.args[0]
                if isinstance(option, ast.Constant) and option.value in {
                    "--lookback-days",
                    "--horizon",
                    "--n-paths",
                    "--w-stress",
                }:
                    defaults = [kw for kw in node.keywords if kw.arg == "default"]
                    if defaults:
                        violations.append((option.value, "CLI default", node.lineno))

    assert violations == []
