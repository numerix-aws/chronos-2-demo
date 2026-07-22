import json
from unittest.mock import MagicMock, patch

import pytest

from chronos2_demo.run_spec import PROFILE, RunSpec, compute_spec_hash
from tools.lambda_.run_chronos2 import handler
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


def _run_spec(execution_id="run-1", conditioning=None):
    payload = {**PROFILE, "conditioning": conditioning, "provenance": PROVENANCE}
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


def _put_input(spec, name, kind):
    uri, digest = s3_io.upload_bytes(
        name.encode(),
        bucket="test-data",
        key=f"runs/{spec.execution_id}/{name}.parquet",
        content_type="application/vnd.apache.parquet",
    )
    run_manifest.put_artifact_sidecar(
        artifact_uri=uri,
        artifact_sha256=digest,
        artifact_kind=kind,
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
    spec = _run_spec(
        conditioning={"series_shifts": {"USDEUR": -0.1}, "n_anchor_days": 30}
    )
    _put_manifest(spec)
    return (
        spec,
        _put_input(spec, "panel", "market_panel"),
        _put_input(spec, "covariates", "covariates"),
    )


def test_launcher_uses_manifest_owned_environment_and_seed_name(launcher_run):
    spec, panel_uri, covariates_uri = launcher_run
    ecs = MagicMock()
    ecs.run_task.return_value = {"tasks": [{"taskArn": "arn:task/chronos"}]}
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
                "covariates_uri": covariates_uri,
                "horizon": 1,
                "n_paths": 2,
                "seed": 99,
            },
            None,
        )

    assert out == {
        "status": "ok",
        "result": {
            "execution_id": spec.execution_id,
            "spec_hash": spec.spec_hash,
            "task_arn": "arn:task/chronos",
            "paths_uri": "s3://test-data/runs/run-1/chronos2.pkl",
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
        "COVARIATES_URI": covariates_uri,
        "OUTPUT_URI": "s3://test-data/runs/run-1/chronos2.pkl",
        "AS_OF": "2022-09-30",
        "CHRONOS2_ENDPOINT": "chronos2-demo",
        "CONDITIONING_JSON": json.dumps(spec.conditioning, sort_keys=True),
        "HORIZON": "252",
        "LOOKBACK_DAYS": "1260",
        "N_PATHS": "500",
        "SEED": "0",
        "PRODUCER_VERSION": "sha256:chronos",
    }
    assert "CHRONOS_SEED" not in values


@pytest.mark.parametrize("foreign_input", ["panel", "covariates"])
def test_launcher_rejects_inputs_from_another_execution(launcher_run, foreign_input):
    spec, panel_uri, covariates_uri = launcher_run
    other_spec = _run_spec("run-2")
    _put_manifest(other_spec)
    replacement = _put_input(
        other_spec,
        foreign_input,
        "market_panel" if foreign_input == "panel" else "covariates",
    )
    event = {
        "execution_id": spec.execution_id,
        "panel_uri": panel_uri,
        "covariates_uri": covariates_uri,
    }
    event[f"{foreign_input}_uri"] = replacement
    ecs = MagicMock()
    real_client = handler.boto3.client

    def client(service_name, *args, **kwargs):
        if service_name == "ecs":
            return ecs
        return real_client(service_name, *args, **kwargs)

    with patch.object(handler.boto3, "client", side_effect=client):
        out = handler.handler(event, None)

    assert out["status"] == "error"
    assert "run prefix" in out["message"]
    ecs.run_task.assert_not_called()
