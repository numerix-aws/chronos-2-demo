"""check_chronos2 tool: poll the launched chronos2 Fargate task.

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
    for override in task.get("overrides", {}).get("containerOverrides", []):
        if override.get("name") == container_name:
            return {
                item["name"]: item["value"]
                for item in override.get("environment", [])
            }
    return {}


@bedrock_action
def handler(event: dict, _ctx) -> dict:
    try:
        spec = run_manifest.load_run_spec(event["execution_id"])
        task_arn = event["task_arn"]
        paths_uri = event["paths_uri"]
    except (KeyError, TypeError, ValueError) as exc:
        return responses.error(f"check_chronos2 validation failed: {exc}")

    desc = _describe_task(task_arn)
    if not desc.get("tasks"):
        return responses.error(f"task {task_arn} not found")
    task = desc["tasks"][0]
    task_environment = _task_environment(task)
    expected_identity = {
        "EXECUTION_ID": spec.execution_id,
        "SPEC_HASH": spec.spec_hash,
        "OUTPUT_URI": paths_uri,
    }
    if task.get("taskArn", task_arn) != task_arn or any(
        task_environment.get(key) != value
        for key, value in expected_identity.items()
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
            f"chronos2 task {task_arn} failed: {reason} "
            f"(exit code {container.get('exitCode')})"
        )
    try:
        meta = run_manifest.validate_artifact(
            paths_uri,
            spec=spec,
            allowed_kinds={"pathset"},
            allowed_sources={"chronos2", "chronos2_conditional"},
        )
    except (TypeError, ValueError) as exc:
        return responses.error(f"check_chronos2 validation failed: {exc}")
    return responses.ok({
        "task_status": status,
        "ready": True,
        "paths_uri": paths_uri,
        **meta.__dict__,
    })
