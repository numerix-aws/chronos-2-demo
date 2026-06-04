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
    assert required == {"session_id", "as_of_date", "lookback_days"}, required


def test_blend_paths_w_stress_constrained_to_unit_interval():
    spec = _load()
    schema = spec["paths"]["/blend_paths"]["post"]["requestBody"][
        "content"
    ]["application/json"]["schema"]
    w = schema["properties"]["w_stress"]
    assert w["minimum"] == 0.0
    assert w["maximum"] == 1.0


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
