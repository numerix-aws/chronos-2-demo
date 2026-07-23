"""The quantitative Gateway path is a fixed, model-independent DAG."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from chronos2_demo.run_spec import canonical_run_payload, compile_run_spec


RUNTIME_DIR = Path(__file__).resolve().parents[1] / "runtime"
PROVENANCE = {
    "market_snapshot_id": "market-v1",
    "market_sha256": "a" * 64,
    "covariate_snapshot_id": "covariates-v1",
    "covariate_sha256": "b" * 64,
    "chronos_endpoint": "chronos2-demo-ep",
    "chronos_model_version": "chronos-2",
    "baseline_image_digest": f"sha256:{'c' * 64}",
    "chronos_image_digest": f"sha256:{'d' * 64}",
    "agent_image_digest": f"sha256:{'e' * 64}",
    "book_version": "cross_asset_demo_v1",
    "blend_version": "importance_weight_v1",
    "pricing_version": "cross_asset_v1",
    "tool_bundle_version": "git:0123456789abcdef",
    "strands_version": "1.30.0",
}
TOOL_NAMES = (
    "load_data",
    "plot",
    "run_baseline_mc",
    "check_baseline_mc",
    "run_chronos2",
    "check_chronos2",
    "blend_paths",
    "price_book",
    "lookup_use_case",
)


def _load_workflow():
    path = RUNTIME_DIR / "workflow.py"
    assert path.exists(), "deterministic workflow is missing"
    spec = importlib.util.spec_from_file_location("runtime_workflow_task8", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _ok(result):
    envelope = {"status": "ok", "result": result}
    return {
        "status": "success",
        "toolUseId": "returned-id",
        "content": [{"text": json.dumps(envelope)}],
    }


def _price(role: str, source: str, paths_uri: str):
    return {
        "execution_id": "run-1",
        "spec_hash": "spec-hash",
        "scenario_role": role,
        "source": source,
        "paths_uri": paths_uri,
        "paths_sha256": f"{role}-paths-sha",
        "metrics_uri": f"s3://data/runs/run-1/metrics/{role}.json",
        "metrics_sha256": f"{role}-metrics-sha",
        "terminal": {"ee": 1.0, "pfe_975": 2.0, "es_975": 3.0},
    }


class FakeClient:
    def __init__(self, *, fail_on: str | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.polls = {"check_baseline_mc": 0, "check_chronos2": 0}
        self.fail_on = fail_on

    def list_tools_sync(self):
        return [
            SimpleNamespace(tool_name=f"chronos-demo___{name}") for name in TOOL_NAMES
        ]

    def call_tool_sync(self, *, tool_use_id, name, arguments):
        canonical = name.rsplit("___", 1)[-1]
        self.calls.append((canonical, arguments))
        if canonical == self.fail_on:
            return {
                "status": "error",
                "toolUseId": tool_use_id,
                "content": [{
                    "text": json.dumps({
                        "status": "error",
                        "message": f"{canonical} unavailable",
                        "details": {"retryable": False},
                    })
                }],
            }
        if canonical == "load_data":
            return _ok({
                "panel_uri": "s3://data/runs/run-1/panel.parquet",
                "covariates_uri": "s3://data/runs/run-1/covariates.parquet",
                "regimes_uri": "s3://data/runs/run-1/regimes.parquet",
            })
        if canonical == "plot":
            return _ok({
                "plot_role": arguments["spec"],
                "image_s3_uri": f"s3://plots/{arguments['spec']}.png",
                "image_uri": f"https://plots/{arguments['spec']}.png",
                "image_sha256": f"{arguments['spec']}-sha",
            })
        if canonical == "run_baseline_mc":
            return _ok({
                "task_arn": "baseline-task",
                "paths_uri": "s3://data/runs/run-1/baseline.pkl",
            })
        if canonical == "check_baseline_mc":
            self.polls[canonical] += 1
            return _ok({
                "ready": self.polls[canonical] == 2,
                "paths_uri": "s3://data/runs/run-1/baseline.pkl",
            })
        if canonical == "run_chronos2":
            return _ok({
                "task_arn": "chronos-task",
                "paths_uri": "s3://data/runs/run-1/chronos2.pkl",
            })
        if canonical == "check_chronos2":
            self.polls[canonical] += 1
            return _ok({
                "ready": self.polls[canonical] == 2,
                "paths_uri": "s3://data/runs/run-1/chronos2.pkl",
            })
        if canonical == "blend_paths":
            return _ok({
                "execution_id": "run-1",
                "spec_hash": "spec-hash",
                "blended_uri": "s3://data/runs/run-1/blended.pkl",
                "diagnostics_uri": "s3://data/runs/run-1/diagnostics.json",
                "diagnostics_sha256": "diagnostics-sha",
                "diagnostics": {"w_stress": 0.5305},
            })
        if canonical == "price_book":
            by_uri = {
                "s3://data/runs/run-1/baseline.pkl": ("baseline", "parametric"),
                "s3://data/runs/run-1/chronos2.pkl": ("chronos_only", "chronos2"),
                "s3://data/runs/run-1/blended.pkl": ("augmented", "blended"),
            }
            role, source = by_uri[arguments["paths_uri"]]
            return _ok(_price(role, source, arguments["paths_uri"]))
        raise AssertionError(f"unexpected tool call: {canonical}")


def _consume(generator):
    events = []
    while True:
        try:
            events.append(next(generator))
        except StopIteration as completed:
            return events, completed.value


def _spec():
    return compile_run_spec(
        "Run the stage-safe headline demo.",
        provenance=PROVENANCE,
        execution_id="run-1",
    )


def test_fixed_dag_repeats_polls_and_emits_structured_results():
    module = _load_workflow()
    client = FakeClient()

    events, result = _consume(
        module.run_quantitative_workflow(client, _spec(), sleep=lambda _delay: None)
    )

    names = [name for name, _arguments in client.calls]
    assert names == [
        "load_data",
        "plot",
        "run_baseline_mc",
        "check_baseline_mc",
        "check_baseline_mc",
        "run_chronos2",
        "check_chronos2",
        "check_chronos2",
        "blend_paths",
        "price_book",
        "price_book",
        "price_book",
        "plot",
    ]
    assert "lookup_use_case" not in names
    assert all(arguments["execution_id"] == "run-1" for _, arguments in client.calls)
    assert [
        arguments["spec"] for name, arguments in client.calls if name == "plot"
    ] == ["regime_ribbon", "pfe_overlay"]
    assert [
        event["scenario_role"]
        for event in events
        if event["type"] == "exposure_result"
    ] == ["baseline", "chronos_only", "augmented"]
    assert [event["type"] for event in events].count("diagnostics") == 1
    assert result["run_spec"] == canonical_run_payload(_spec())
    json.dumps(result, sort_keys=True, allow_nan=False)


def test_every_call_emits_running_and_terminal_lifecycle():
    module = _load_workflow()
    client = FakeClient()

    events, _ = _consume(
        module.run_quantitative_workflow(client, _spec(), sleep=lambda _delay: None)
    )

    lifecycle = [event for event in events if event["type"] == "tool"]
    assert len(lifecycle) == len(client.calls) * 2
    for index in range(0, len(lifecycle), 2):
        assert lifecycle[index]["status"] == "running"
        assert lifecycle[index + 1]["status"] == "done"
        assert lifecycle[index]["tool_use_id"] == lifecycle[index + 1]["tool_use_id"]


def test_tool_failure_preserves_structured_error_and_aborts_immediately():
    module = _load_workflow()
    client = FakeClient(fail_on="run_baseline_mc")
    generator = module.run_quantitative_workflow(
        client, _spec(), sleep=lambda _delay: None
    )
    events = []

    with pytest.raises(
        RuntimeError, match="run_baseline_mc failed: run_baseline_mc unavailable"
    ):
        while True:
            events.append(next(generator))

    assert [name for name, _arguments in client.calls] == [
        "load_data",
        "plot",
        "run_baseline_mc",
    ]
    failed = [
        event for event in events
        if event["type"] == "tool" and event["status"] == "failed"
    ]
    assert failed[0]["result"] == {
        "status": "error",
        "message": "run_baseline_mc unavailable",
        "details": {"retryable": False},
    }


def test_decoder_supports_strands_content_objects_and_dict_doubles():
    module = _load_workflow()
    envelope = {"status": "ok", "result": {"value": 7}}

    assert module._decode_call_result({
        "status": "success",
        "content": [{"text": json.dumps(envelope)}],
    }) == envelope
    assert module._decode_call_result(SimpleNamespace(
        status="success",
        content=[SimpleNamespace(text=json.dumps(envelope))],
    )) == envelope
    assert module._decode_call_result({
        "status": "success",
        "content": [{"text": "redundant"}],
        "structuredContent": envelope,
    }) == envelope


@pytest.mark.parametrize("raw", [
    {"status": "success", "content": []},
    {"status": "success", "content": [{"text": "not-json"}]},
    {"status": "success", "content": [{"text": "[]"}]},
    {"status": "success", "content": [{"json": {"result": {}}}]},
])
def test_decoder_rejects_malformed_success_envelopes(raw):
    module = _load_workflow()
    with pytest.raises(RuntimeError):
        module._decode_call_result(raw)


def test_runtime_dependency_is_exactly_pinned():
    requirements = (RUNTIME_DIR / "requirements.txt").read_text().splitlines()
    assert "strands-agents==1.30.0" in requirements
    assert not any(line.startswith("strands-agents>") for line in requirements)
