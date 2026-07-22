"""check_baseline_mc tool: poll the launched baseline-MC Fargate task.

Inputs:  {"execution_id": str, "task_arn": str, "paths_uri": str}
Outputs: {"task_status": str, "ready": bool, "paths_uri": str}
"""
from __future__ import annotations
import os

import boto3

from tools.lambda_.shared import responses, run_manifest
from tools.lambda_.shared.bedrock import bedrock_action


def _describe_task(task_arn: str) -> dict:
    return boto3.client("ecs").describe_tasks(
        cluster=os.environ["CLUSTER_ARN"], tasks=[task_arn]
    )


def _task_environment(task: dict) -> dict[str, str]:
    container_name = os.environ["CONTAINER_NAME"]
    overrides = [
        override
        for override in task.get("overrides", {}).get("containerOverrides", [])
        if override.get("name") == container_name
    ]
    if len(overrides) != 1:
        return {}
    items = overrides[0].get("environment", [])
    environment = {item["name"]: item["value"] for item in items}
    return environment if len(environment) == len(items) else {}


def _expected_task_environment(spec, output_uri: str) -> dict[str, str]:
    prefix = f"s3://{os.environ['DATA_BUCKET']}/runs/{spec.execution_id}"
    return {
        "EXECUTION_ID": spec.execution_id,
        "SPEC_HASH": spec.spec_hash,
        "PANEL_URI": f"{prefix}/panel.parquet",
        "OUTPUT_URI": output_uri,
        "AS_OF": spec.as_of_date,
        "HORIZON": str(spec.horizon),
        "N_PATHS": str(spec.n_paths),
        "N_COMPONENTS": str(spec.baseline_components),
        "SEED": str(spec.baseline_seed),
        "PRODUCER_VERSION": spec.provenance["baseline_image_digest"],
    }


@bedrock_action
def handler(event: dict, _ctx) -> dict:
    try:
        spec = run_manifest.load_run_spec(event["execution_id"])
        task_arn = event["task_arn"]
        paths_uri = event["paths_uri"]
    except (KeyError, TypeError, ValueError) as exc:
        return responses.error(f"check_baseline_mc validation failed: {exc}")

    output_uri = (
        f"s3://{os.environ['DATA_BUCKET']}/runs/{spec.execution_id}/baseline.pkl"
    )
    if paths_uri != output_uri:
        return responses.error(
            f"paths_uri does not match canonical output {output_uri}"
        )

    desc = _describe_task(task_arn)
    if not desc.get("tasks"):
        return responses.error(f"task {task_arn} not found")
    task = desc["tasks"][0]
    task_environment = _task_environment(task)
    expected_environment = _expected_task_environment(spec, output_uri)
    # The launcher emits exactly this map, so equality makes the described ECS
    # override the immutable launch record without a second persistence layer.
    if (
        task.get("taskArn", task_arn) != task_arn
        or task_environment != expected_environment
    ):
        return responses.error(
            f"task {task_arn} does not belong to execution {spec.execution_id}"
        )
    status = task["lastStatus"]

    if status != "STOPPED":
        return responses.ok({
            "execution_id": spec.execution_id,
            "spec_hash": spec.spec_hash,
            "task_status": status,
            "ready": False,
            "paths_uri": paths_uri,
        })

    container = next(
        (
            item
            for item in task.get("containers", [])
            if item.get("name") == os.environ["CONTAINER_NAME"]
        ),
        {},
    )
    if container.get("exitCode") != 0:
        reason = container.get("reason") or task.get("stoppedReason") or "unknown reason"
        return responses.error(
            f"baseline MC task {task_arn} failed: {reason} "
            f"(exit code {container.get('exitCode')})"
        )
    try:
        meta = run_manifest.validate_artifact(
            output_uri,
            spec=spec,
            allowed_kinds={"pathset"},
            allowed_sources={"parametric"},
        )
    except (TypeError, ValueError) as exc:
        return responses.error(f"check_baseline_mc validation failed: {exc}")
    if meta.producer_version != spec.provenance["baseline_image_digest"]:
        return responses.error(
            "check_baseline_mc validation failed: artifact producer mismatch"
        )
    return responses.ok({
        "task_status": status,
        "ready": True,
        "paths_uri": output_uri,
        **meta.__dict__,
    })
