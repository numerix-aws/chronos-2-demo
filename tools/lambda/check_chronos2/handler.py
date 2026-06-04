"""check_chronos2 tool: poll the launched chronos2 Fargate task.

Inputs:  {"task_arn": str, "paths_uri": str}
Outputs: {"task_status": str, "ready": bool, "paths_uri": str}
"""
from __future__ import annotations
import os

import boto3

from tools.lambda_.shared import responses
from tools.lambda_.shared.bedrock import bedrock_action


def _describe_task(task_arn: str) -> dict:
    return boto3.client("ecs").describe_tasks(
        cluster=os.environ["CLUSTER_ARN"], tasks=[task_arn]
    )


@bedrock_action
def handler(event: dict, _ctx) -> dict:
    task_arn = event.get("task_arn")
    paths_uri = event.get("paths_uri")
    if not task_arn:
        return responses.error("missing task_arn")

    desc = _describe_task(task_arn)
    if not desc.get("tasks"):
        return responses.error(f"task {task_arn} not found")
    task = desc["tasks"][0]
    status = task["lastStatus"]

    if status != "STOPPED":
        return responses.ok({"task_status": status, "ready": False, "paths_uri": paths_uri})

    exit_codes = [c.get("exitCode") for c in task.get("containers", [])]
    if any(code not in (0, None) for code in exit_codes):
        return responses.error(f"chronos2 task failed (exit codes {exit_codes})")
    return responses.ok({"task_status": status, "ready": True, "paths_uri": paths_uri})
