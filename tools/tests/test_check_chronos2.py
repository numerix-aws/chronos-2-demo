import json
from unittest.mock import patch

import pytest

from chronos2_demo.run_spec import (
    PROFILE,
    RunSpec,
    canonical_run_payload,
    compute_spec_hash,
)
from tools.lambda_.check_chronos2 import handler
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


def _stage_poll_run(monkeypatch, conditioning=None, source=None):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("CLUSTER_ARN", "chronos2")
    monkeypatch.setenv("CONTAINER_NAME", "App")
    payload = {**PROFILE, "conditioning": conditioning, "provenance": PROVENANCE}
    spec = RunSpec(
        **payload,
        spec_hash=compute_spec_hash(payload),
        execution_id="run-1",
    )
    s3_io.upload_json(
        spec.__dict__, bucket="test-data", key="runs/run-1/run_spec.json"
    )
    uri, digest = s3_io.upload_bytes(
        b"pathset bytes",
        bucket="test-data",
        key="runs/run-1/chronos2.pkl",
        content_type="application/octet-stream",
    )
    run_manifest.put_artifact_sidecar(
        artifact_uri=uri,
        artifact_sha256=digest,
        artifact_kind="pathset",
        source=source or ("chronos2_conditional" if conditioning else "chronos2"),
        spec=spec,
        producer_version="sha256:chronos",
    )
    return spec, uri


@pytest.fixture
def poll_run(s3, monkeypatch):
    return _stage_poll_run(monkeypatch)


def _describe(spec, paths_uri, status, exit_code=None, reason=None, execution_id=None):
    container = {"name": "App", "lastStatus": status}
    if exit_code is not None:
        container["exitCode"] = exit_code
    if reason is not None:
        container["reason"] = reason
    conditioning = canonical_run_payload(spec)["conditioning"]
    environment = {
        "EXECUTION_ID": execution_id or spec.execution_id,
        "SPEC_HASH": spec.spec_hash,
        "PANEL_URI": f"s3://test-data/runs/{spec.execution_id}/panel.parquet",
        "COVARIATES_URI": f"s3://test-data/runs/{spec.execution_id}/covariates.parquet",
        "OUTPUT_URI": paths_uri,
        "AS_OF": spec.as_of_date,
        "CHRONOS2_ENDPOINT": spec.provenance["chronos_endpoint"],
        "CONDITIONING_JSON": (
            json.dumps(conditioning, sort_keys=True) if conditioning else ""
        ),
        "HORIZON": str(spec.horizon),
        "LOOKBACK_DAYS": str(spec.lookback_days),
        "N_PATHS": str(spec.n_paths),
        "SEED": str(spec.chronos_seed),
        "PRODUCER_VERSION": spec.provenance["chronos_image_digest"],
    }
    return {
        "tasks": [{
            "taskArn": "arn:task/chronos",
            "lastStatus": status,
            "containers": [container],
            "overrides": {
                "containerOverrides": [{
                    "name": "App",
                    "environment": [
                        {"name": key, "value": value}
                        for key, value in environment.items()
                    ],
                }]
            },
        }],
        "failures": [],
    }


def test_check_reports_running_without_validating_output(poll_run):
    spec, uri = poll_run
    with patch.object(
        handler, "_describe_task", return_value=_describe(spec, uri, "RUNNING")
    ), patch.object(handler.run_manifest, "validate_artifact") as validate:
        out = handler.handler(
            {"execution_id": "run-1", "task_arn": "arn:task/chronos", "paths_uri": uri},
            None,
        )

    assert out["result"] == {
        "execution_id": "run-1",
        "spec_hash": spec.spec_hash,
        "task_status": "RUNNING",
        "ready": False,
        "paths_uri": uri,
    }
    validate.assert_not_called()


def test_check_returns_validated_sidecar_only_after_success(poll_run):
    spec, uri = poll_run
    with patch.object(
        handler, "_describe_task", return_value=_describe(spec, uri, "STOPPED", 0)
    ):
        out = handler.handler(
            {"execution_id": "run-1", "task_arn": "arn:task/chronos", "paths_uri": uri},
            None,
        )

    assert out["status"] == "ok"
    assert out["result"]["ready"] is True
    assert out["result"]["artifact_uri"] == uri
    assert out["result"]["source"] == "chronos2"
    assert out["result"]["scenario_role"] == "chronos_only"
    assert out["result"]["producer_version"] == "sha256:chronos"


def test_check_rejects_task_owned_by_another_execution(poll_run):
    spec, uri = poll_run
    with patch.object(
        handler,
        "_describe_task",
        return_value=_describe(spec, uri, "RUNNING", execution_id="run-2"),
    ):
        out = handler.handler(
            {"execution_id": "run-1", "task_arn": "arn:task/chronos", "paths_uri": uri},
            None,
        )

    assert out["status"] == "error"
    assert "does not belong" in out["message"]


def test_check_reports_nonzero_exit_with_reason_and_task_arn(poll_run):
    spec, uri = poll_run
    with patch.object(
        handler,
        "_describe_task",
        return_value=_describe(spec, uri, "STOPPED", 17, "inference failed"),
    ):
        out = handler.handler(
            {"execution_id": "run-1", "task_arn": "arn:task/chronos", "paths_uri": uri},
            None,
        )

    assert out["status"] == "error"
    assert "inference failed" in out["message"]
    assert "arn:task/chronos" in out["message"]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("LOOKBACK_DAYS", "504"),
        ("N_PATHS", "2"),
        ("COVARIATES_URI", "s3://test-data/runs/run-1/alternate.parquet"),
        ("PRODUCER_VERSION", "sha256:forged"),
    ],
)
def test_check_rejects_same_execution_with_altered_chronos_override(
    poll_run, name, value
):
    spec, uri = poll_run
    task = _describe(spec, uri, "STOPPED", 0)
    environment = task["tasks"][0]["overrides"]["containerOverrides"][0][
        "environment"
    ]
    next(item for item in environment if item["name"] == name)["value"] = value

    with patch.object(handler, "_describe_task", return_value=task), patch.object(
        handler.run_manifest, "validate_artifact"
    ) as validate:
        out = handler.handler(
            {"execution_id": "run-1", "task_arn": "arn:task/chronos", "paths_uri": uri},
            None,
        )

    assert out["status"] == "error"
    assert "does not belong" in out["message"]
    validate.assert_not_called()


def test_check_rejects_noncanonical_caller_output_even_when_task_matches(poll_run):
    spec, _uri = poll_run
    alternate_uri = "s3://test-data/runs/run-1/alternate.pkl"
    task = _describe(spec, alternate_uri, "RUNNING")

    with patch.object(handler, "_describe_task", return_value=task):
        out = handler.handler(
            {
                "execution_id": "run-1",
                "task_arn": "arn:task/chronos",
                "paths_uri": alternate_uri,
            },
            None,
        )

    assert out["status"] == "error"
    assert "canonical output" in out["message"]


def test_unconditioned_run_rejects_conditional_chronos_source(s3, monkeypatch):
    spec, uri = _stage_poll_run(
        monkeypatch,
        source="chronos2_conditional",
    )

    with patch.object(
        handler, "_describe_task", return_value=_describe(spec, uri, "STOPPED", 0)
    ):
        out = handler.handler(
            {"execution_id": "run-1", "task_arn": "arn:task/chronos", "paths_uri": uri},
            None,
        )

    assert out["status"] == "error"
    assert "source" in out["message"]


def test_conditioned_run_rejects_unconditional_chronos_source(s3, monkeypatch):
    conditioning = {"series_shifts": {"USDEUR": -0.1}, "n_anchor_days": 30}
    spec, uri = _stage_poll_run(
        monkeypatch,
        conditioning=conditioning,
        source="chronos2",
    )

    with patch.object(
        handler, "_describe_task", return_value=_describe(spec, uri, "STOPPED", 0)
    ):
        out = handler.handler(
            {"execution_id": "run-1", "task_arn": "arn:task/chronos", "paths_uri": uri},
            None,
        )

    assert out["status"] == "error"
    assert "source" in out["message"]


def test_conditioned_run_accepts_conditional_chronos_source(s3, monkeypatch):
    conditioning = {"series_shifts": {"USDEUR": -0.1}, "n_anchor_days": 30}
    spec, uri = _stage_poll_run(monkeypatch, conditioning=conditioning)

    with patch.object(
        handler, "_describe_task", return_value=_describe(spec, uri, "STOPPED", 0)
    ):
        out = handler.handler(
            {"execution_id": "run-1", "task_arn": "arn:task/chronos", "paths_uri": uri},
            None,
        )

    assert out["status"] == "ok"
    assert out["result"]["source"] == "chronos2_conditional"


def test_check_rejects_forged_chronos_producer_digest(poll_run):
    spec, uri = poll_run
    forged = s3_io.download_json(run_manifest.sidecar_uri(uri))
    forged["producer_version"] = "sha256:forged"
    s3_io.upload_json(
        forged,
        bucket="test-data",
        key="runs/run-1/chronos2.meta.json",
    )

    with patch.object(
        handler, "_describe_task", return_value=_describe(spec, uri, "STOPPED", 0)
    ):
        out = handler.handler(
            {"execution_id": "run-1", "task_arn": "arn:task/chronos", "paths_uri": uri},
            None,
        )

    assert out["status"] == "error"
    assert "producer" in out["message"]
