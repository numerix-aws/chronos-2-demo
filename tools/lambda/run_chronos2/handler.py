"""run_chronos2 tool: launch the chronos2 Fargate task (async).

Inputs:  {"execution_id": str, "panel_uri": str, "covariates_uri": str}
Outputs: {"task_arn": str, "paths_uri": str}

Returns immediately; the result PathSet lands at `paths_uri` when the task
finishes. Poll with `check_chronos2`. The chronos2 endpoint call (AutoGluon
Cloud) runs in the Fargate container, not here.
"""
from __future__ import annotations
import json
import os

import boto3

from chronos2_demo.run_spec import canonical_run_payload
from tools.lambda_.shared import responses, run_manifest
from tools.lambda_.shared.bedrock import bedrock_action


@bedrock_action
def handler(event: dict, _ctx) -> dict:
    try:
        spec = run_manifest.load_run_spec(event["execution_id"])
        panel_uri = event["panel_uri"]
        covariates_uri = event["covariates_uri"]
        run_manifest.validate_artifact(
            panel_uri,
            spec=spec,
            allowed_kinds={"market_panel"},
        )
        run_manifest.validate_artifact(
            covariates_uri,
            spec=spec,
            allowed_kinds={"covariates"},
        )
    except (KeyError, TypeError, ValueError) as exc:
        return responses.error(f"run_chronos2 validation failed: {exc}")

    bucket = os.environ["DATA_BUCKET"]
    output_uri = f"s3://{bucket}/runs/{spec.execution_id}/chronos2.pkl"
    conditioning = canonical_run_payload(spec)["conditioning"]
    environment = {
        "EXECUTION_ID": spec.execution_id,
        "SPEC_HASH": spec.spec_hash,
        "PANEL_URI": panel_uri,
        "COVARIATES_URI": covariates_uri,
        "OUTPUT_URI": output_uri,
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
    env = [
        {"name": key, "value": value}
        for key, value in environment.items()
    ]

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
        "execution_id": spec.execution_id,
        "spec_hash": spec.spec_hash,
        "task_arn": task_arn,
        "paths_uri": output_uri,
    })
