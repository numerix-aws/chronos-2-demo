"""run_chronos2 tool: launch the chronos2 Fargate task (async).

Inputs:  {"panel_uri": str, "as_of": "YYYY-MM-DD", "horizon": int,
          "n_paths": int, "covariates_uri": str?, "conditioning": dict?,
          "seed": int?}
Outputs: {"task_arn": str, "paths_uri": str}

Returns immediately; the result PathSet lands at `paths_uri` when the task
finishes. Poll with `check_chronos2`. The chronos2 endpoint call (AutoGluon
Cloud) runs in the Fargate container, not here.
"""
from __future__ import annotations
import json
import os
import uuid

import boto3

from tools.lambda_.shared import responses
from tools.lambda_.shared.bedrock import bedrock_action


@bedrock_action
def handler(event: dict, _ctx) -> dict:
    horizon = int(event.get("horizon", 0))
    n_paths = int(event.get("n_paths", 0))
    if horizon <= 0 or horizon > 1000:
        return responses.error("horizon must be in (0, 1000]")
    if n_paths <= 0 or n_paths > 20_000:
        return responses.error("n_paths must be in (0, 20000]")
    try:
        panel_uri = event["panel_uri"]
        as_of = event["as_of"]
    except KeyError as e:
        return responses.error(f"missing input: {e}")

    bucket = os.environ["DATA_BUCKET"]
    sid = uuid.uuid4().hex[:12]
    output_key = f"sessions/{sid}/chronos2.pkl"

    env = [
        {"name": "DATA_BUCKET", "value": bucket},
        {"name": "PANEL_URI", "value": panel_uri},
        {"name": "AS_OF", "value": as_of},
        {"name": "HORIZON", "value": str(horizon)},
        {"name": "N_PATHS", "value": str(n_paths)},
        {"name": "OUTPUT_KEY", "value": output_key},
        {"name": "CHRONOS2_ENDPOINT", "value": os.environ["CHRONOS2_ENDPOINT"]},
        {"name": "SEED", "value": str(int(event.get("seed", 0)))},
    ]
    if event.get("covariates_uri"):
        env.append({"name": "COVARIATES_URI", "value": event["covariates_uri"]})
    if event.get("conditioning"):
        env.append({"name": "CONDITIONING_JSON", "value": json.dumps(event["conditioning"])})

    overrides = {"containerOverrides": [{"name": os.environ["CONTAINER_NAME"], "environment": env}]}
    network = {
        "awsvpcConfiguration": {
            "subnets": os.environ["SUBNET_IDS"].split(","),
            "securityGroups": [g for g in os.environ.get("SECURITY_GROUP_IDS", "").split(",") if g],
            "assignPublicIp": "DISABLED",
        }
    }
    resp = boto3.client("ecs").run_task(
        cluster=os.environ["CLUSTER_ARN"],
        taskDefinition=os.environ["TASK_DEFINITION_ARN"],
        launchType="FARGATE",
        overrides=overrides,
        networkConfiguration=network,
        count=1,
    )
    task_arn = resp["tasks"][0]["taskArn"]
    return responses.ok({
        "task_arn": task_arn,
        "paths_uri": f"s3://{bucket}/{output_key}",
    })
