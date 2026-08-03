from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from chronos2_demo.run_spec import PROFILE, RunSpec, compute_spec_hash
from tools.lambda_.run_baseline_mc import handler
from tools.lambda_.shared import run_manifest, s3_io


PROVENANCE = {
    "market_snapshot_id": "market-v1",
    "market_sha256": "a" * 64,
    "covariate_snapshot_id": "covariates-v1",
    "covariate_sha256": "b" * 64,
    "chronos_endpoint": "chronos2-demo",
    "baseline_image_digest": "sha256:baseline",
    "chronos_image_digest": "sha256:chronos",
    "agent_image_digest": "sha256:agent",
    "book_version": "cross_asset_demo_v1",
    "blend_version": "importance_weight_v1",
    "pricing_version": "cross_asset_v1",
    "tool_bundle_version": "git:test",
    "strands_version": "1.30.0",
}


def test_launcher_handler_imports_without_pandas():
    repo_root = Path(__file__).resolve().parents[2]
    lambda_dir = repo_root / "tools" / "lambda"
    script = f"""
import builtins
import sys
import types

lambda_pkg = types.ModuleType("tools.lambda_")
lambda_pkg.__path__ = [{str(lambda_dir)!r}]
sys.modules["tools.lambda_"] = lambda_pkg

real_import = builtins.__import__
def block_pandas(name, *args, **kwargs):
    if name == "pandas" or name.startswith("pandas."):
        raise ModuleNotFoundError("pandas is not installed in the light layer")
    return real_import(name, *args, **kwargs)
builtins.__import__ = block_pandas

from tools.lambda_.run_baseline_mc import handler
assert callable(handler.handler)
"""
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )


def _run_spec(execution_id="run-1"):
    payload = {**PROFILE, "provenance": PROVENANCE}
    return RunSpec(
        **payload,
        spec_hash=compute_spec_hash(payload),
        execution_id=execution_id,
    )


def _put_manifest(spec):
    s3_io.upload_json(
        spec.__dict__,
        bucket="test-data",
        key=f"runs/{spec.execution_id}/run_spec.json",
    )


def _put_panel(spec):
    uri, digest = s3_io.upload_bytes(
        b"staged panel",
        bucket="test-data",
        key=f"runs/{spec.execution_id}/panel.parquet",
        content_type="application/vnd.apache.parquet",
    )
    run_manifest.put_artifact_sidecar(
        artifact_uri=uri,
        artifact_sha256=digest,
        artifact_kind="market_panel",
        spec=spec,
        producer_version="git:test",
    )
    return uri


@pytest.fixture
def launcher_run(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("CLUSTER_ARN", "cluster")
    monkeypatch.setenv("TASK_DEFINITION_ARN", "task-def")
    monkeypatch.setenv("CONTAINER_NAME", "App")
    monkeypatch.setenv("SUBNET_IDS", "subnet-1")
    monkeypatch.setenv("SECURITY_GROUP_IDS", "sg-1")
    spec = _run_spec()
    _put_manifest(spec)
    return spec, _put_panel(spec)


def test_launcher_uses_manifest_owned_environment_and_deterministic_output(launcher_run):
    spec, panel_uri = launcher_run
    ecs = MagicMock()
    ecs.run_task.return_value = {"tasks": [{"taskArn": "arn:task/baseline"}]}
    real_client = handler.boto3.client

    def client(service_name, *args, **kwargs):
        if service_name == "ecs":
            return ecs
        return real_client(service_name, *args, **kwargs)

    with patch.object(handler.boto3, "client", side_effect=client), patch.object(
        handler.run_manifest,
        "load_run_spec",
        wraps=handler.run_manifest.load_run_spec,
    ) as load_run_spec:
        out = handler.handler(
            {
                "execution_id": spec.execution_id,
                "panel_uri": panel_uri,
                "horizon": 1,
                "n_paths": 2,
                "n_components": 1,
                "seed": 99,
            },
            None,
        )

    assert out == {
        "status": "ok",
        "result": {
            "execution_id": spec.execution_id,
            "spec_hash": spec.spec_hash,
            "task_arn": "arn:task/baseline",
            "paths_uri": "s3://test-data/runs/run-1/baseline.pkl",
        },
    }
    load_run_spec.assert_called_once_with("run-1")
    values = {
        item["name"]: item["value"]
        for item in ecs.run_task.call_args.kwargs["overrides"]
        ["containerOverrides"][0]["environment"]
    }
    assert values == {
        "EXECUTION_ID": "run-1",
        "SPEC_HASH": spec.spec_hash,
        "PANEL_URI": panel_uri,
        "OUTPUT_URI": "s3://test-data/runs/run-1/baseline.pkl",
        "AS_OF": "2022-09-30",
        "HORIZON": "252",
        "N_PATHS": "500",
        "N_COMPONENTS": "5",
        "SEED": "0",
        "PRODUCER_VERSION": "sha256:baseline",
    }


def test_launcher_rejects_panel_from_another_execution(launcher_run):
    spec, _ = launcher_run
    other_spec = _run_spec("run-2")
    _put_manifest(other_spec)
    other_panel_uri = _put_panel(other_spec)
    ecs = MagicMock()
    real_client = handler.boto3.client

    def client(service_name, *args, **kwargs):
        if service_name == "ecs":
            return ecs
        return real_client(service_name, *args, **kwargs)

    with patch.object(handler.boto3, "client", side_effect=client):
        out = handler.handler(
            {"execution_id": spec.execution_id, "panel_uri": other_panel_uri},
            None,
        )

    assert out["status"] == "error"
    assert "run prefix" in out["message"]
    ecs.run_task.assert_not_called()
