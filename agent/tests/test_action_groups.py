"""Validate that action_groups.json matches the locked tool contracts."""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
ACTION_GROUPS = ROOT / "action_groups.json"

EXPECTED_OPERATIONS = {
    "load_data",
    "run_baseline_mc",
    "check_baseline_mc",
    "run_chronos2",
    "check_chronos2",
    "blend_paths",
    "price_book",
    "plot",
    "lookup_use_case",
}


def _load() -> dict:
    return json.loads(ACTION_GROUPS.read_text())


def test_file_is_valid_openapi_3_0():
    spec = _load()
    assert spec["openapi"].startswith("3.0"), spec["openapi"]
    assert "paths" in spec and spec["paths"], "no paths defined"


def test_every_required_tool_has_a_path():
    spec = _load()
    op_ids = {
        op["operationId"]
        for path in spec["paths"].values()
        for op in path.values()
        if isinstance(op, dict) and "operationId" in op
    }
    missing = EXPECTED_OPERATIONS - op_ids
    assert not missing, f"missing tool operations: {sorted(missing)}"


def test_each_request_schema_is_valid():
    spec = _load()
    for path, methods in spec["paths"].items():
        for verb, op in methods.items():
            if not isinstance(op, dict) or "requestBody" not in op:
                continue
            schema = op["requestBody"]["content"]["application/json"]["schema"]
            # Will raise if schema itself is malformed.
            Draft202012Validator.check_schema(schema)


def test_load_data_envelope_matches_lambda_contract():
    spec = _load()
    schema = spec["paths"]["/load_data"]["post"]["requestBody"][
        "content"
    ]["application/json"]["schema"]
    required = set(schema.get("required", []))
    assert required == {"session_id", "execution_id"}, required
    assert set(schema["properties"]) == required

    response_schema = spec["paths"]["/load_data"]["post"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    assert set(response_schema["required"]) == {
        "execution_id",
        "spec_hash",
        "panel_uri",
        "panel_sha256",
        "covariates_uri",
        "covariates_sha256",
        "regimes_uri",
        "regimes_sha256",
        "n_rows",
        "as_of_date",
    }


def test_quantitative_tools_accept_only_manifest_identity_artifacts_and_display_choices():
    spec = _load()
    expected = {
        "/load_data": {"session_id", "execution_id"},
        "/run_baseline_mc": {"execution_id", "panel_uri"},
        "/check_baseline_mc": {"execution_id", "task_arn", "paths_uri"},
        "/run_chronos2": {"execution_id", "panel_uri", "covariates_uri"},
        "/check_chronos2": {"execution_id", "task_arn", "paths_uri"},
        "/blend_paths": {"execution_id", "parametric_uri", "chronos2_uri"},
        "/price_book": {"execution_id", "paths_uri"},
    }
    for path, fields in expected.items():
        schema = spec["paths"][path]["post"]["requestBody"]["content"][
            "application/json"
        ]["schema"]
        assert set(schema["required"]) == fields
        assert set(schema["properties"]) == fields


def test_manifest_owned_quantitative_scalars_are_not_tool_inputs():
    spec = _load()
    forbidden = {
        "as_of",
        "as_of_date",
        "lookback_days",
        "horizon",
        "n_paths",
        "n_components",
        "seed",
        "conditioning",
        "w_stress",
        "book_id",
        "threshold",
    }
    for path, operation in spec["paths"].items():
        if path == "/lookup_use_case":
            continue
        properties = operation["post"]["requestBody"]["content"][
            "application/json"
        ]["schema"]["properties"]
        assert forbidden.isdisjoint(properties), path


@pytest.mark.parametrize("op_id", sorted(EXPECTED_OPERATIONS))
def test_every_operation_documents_responses(op_id):
    spec = _load()
    found = False
    for path, methods in spec["paths"].items():
        for op in methods.values():
            if isinstance(op, dict) and op.get("operationId") == op_id:
                assert "200" in op["responses"], f"{op_id} missing 200 response"
                found = True
    assert found, f"{op_id} not found in spec"


def test_plot_schema_enforces_role_dependent_inputs():
    spec = _load()
    schema = spec["paths"]["/plot"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    assert set(schema["required"]) == {"execution_id", "spec"}
    validator = Draft202012Validator(schema)

    valid = [
        {
            "execution_id": "run-1",
            "spec": "pfe_overlay",
            "baseline_uri": "s3://data/baseline.json",
            "augmented_uri": "s3://data/augmented.json",
        },
        {
            "execution_id": "run-1",
            "spec": "path_fan",
            "paths_uri": "s3://data/paths.pkl",
            "series": "USD_10Y",
        },
        {
            "execution_id": "run-1",
            "spec": "regime_ribbon",
            "regimes_uri": "s3://data/regimes.parquet",
        },
    ]
    for payload in valid:
        assert not list(validator.iter_errors(payload)), payload

    invalid = [
        {"execution_id": "run-1", "spec": "pfe_overlay"},
        {"execution_id": "run-1", "spec": "path_fan", "paths_uri": "s3://data/x.pkl"},
        {"execution_id": "run-1", "spec": "regime_ribbon"},
    ]
    for payload in invalid:
        assert list(validator.iter_errors(payload)), payload


def test_lookup_use_case_supports_catalog_discovery():
    spec = _load()
    operation = spec["paths"]["/lookup_use_case"]["post"]
    request_schema = operation["requestBody"]["content"]["application/json"][
        "schema"
    ]
    assert "topic" not in request_schema.get("required", [])

    response_schema = operation["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert response_schema["type"] == "object"
    assert not response_schema.get("required")
    assert set(response_schema["properties"]) == {
        "topics",
        "topic",
        "summary",
        "markdown",
    }
    assert response_schema["properties"]["topics"]["type"] == "array"
    assert "execution_id" not in request_schema["properties"]


def _request_property(spec: dict, path: str, name: str) -> dict:
    return spec["paths"][path]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]["properties"][name]


def test_natural_language_parameters_are_described_in_business_terms():
    spec = _load()

    for path in spec["paths"]:
        if path == "/lookup_use_case":
            continue
        description = _request_property(spec, path, "execution_id")["description"].lower()
        assert "run" in description

    panel = _request_property(spec, "/run_baseline_mc", "panel_uri")[
        "description"
    ].lower()
    covariates = _request_property(spec, "/run_chronos2", "covariates_uri")[
        "description"
    ].lower()
    chart = _request_property(spec, "/plot", "spec")["description"].lower()
    assert "aligned market history" in panel
    assert "conditioning" in covariates
    assert "chart type" in chart


def test_response_schemas_retain_run_identity_and_artifact_hashes():
    spec = _load()
    expected = {
        "/run_baseline_mc": {"execution_id", "spec_hash", "task_arn", "paths_uri"},
        "/check_baseline_mc": {"execution_id", "spec_hash", "paths_uri", "artifact_sha256"},
        "/run_chronos2": {"execution_id", "spec_hash", "task_arn", "paths_uri"},
        "/check_chronos2": {"execution_id", "spec_hash", "paths_uri", "artifact_sha256"},
        "/blend_paths": {
            "execution_id",
            "spec_hash",
            "blended_uri",
            "blended_sha256",
            "diagnostics_uri",
            "diagnostics_sha256",
        },
        "/price_book": {
            "execution_id",
            "spec_hash",
            "scenario_role",
            "source",
            "paths_uri",
            "paths_sha256",
            "metrics_uri",
            "metrics_sha256",
            "terminal",
        },
        "/plot": {
            "execution_id",
            "spec_hash",
            "plot_role",
            "image_s3_uri",
            "image_uri",
            "image_sha256",
        },
    }
    for path, fields in expected.items():
        response = spec["paths"][path]["post"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert fields <= set(response["properties"]), path
