"""run_baseline_mc tool: launch the baseline-MC Fargate task (async).

Inputs:  {"execution_id": str, "panel_uri": str}
Outputs: {"task_arn": str, "paths_uri": str}

Returns immediately; the result PathSet lands at `paths_uri` when the task
finishes. Poll with `check_baseline_mc`.
"""
from __future__ import annotations
import os

import boto3

from tools.lambda_.shared import responses, run_manifest
from tools.lambda_.shared.bedrock import bedrock_action


@bedrock_action
def handler(event: dict, _ctx) -> dict:
    try:
        spec = run_manifest.load_run_spec(event["execution_id"])
        panel_uri = event["panel_uri"]
        run_manifest.validate_artifact(
            panel_uri,
            spec=spec,
            allowed_kinds={"market_panel"},
        )
    except (KeyError, TypeError, ValueError) as exc:
        return responses.error(f"run_baseline_mc validation failed: {exc}")

    bucket = os.environ["DATA_BUCKET"]
    output_uri = f"s3://{bucket}/runs/{spec.execution_id}/baseline.pkl"
    environment = {
        "EXECUTION_ID": spec.execution_id,
        "SPEC_HASH": spec.spec_hash,
        "PANEL_URI": panel_uri,
        "OUTPUT_URI": output_uri,
        "AS_OF": spec.as_of_date,
        "HORIZON": str(spec.horizon),
        "N_PATHS": str(spec.n_paths),
        "N_COMPONENTS": str(spec.baseline_components),
        "SEED": str(spec.baseline_seed),
        "PRODUCER_VERSION": spec.provenance["baseline_image_digest"],
    }

    overrides = {
        "containerOverrides": [{
            "name": os.environ["CONTAINER_NAME"],
            "environment": [
                {"name": key, "value": value}
                for key, value in environment.items()
            ],
        }],
    }
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
        "execution_id": spec.execution_id,
        "spec_hash": spec.spec_hash,
        "task_arn": task_arn,
        "paths_uri": output_uri,
    })
