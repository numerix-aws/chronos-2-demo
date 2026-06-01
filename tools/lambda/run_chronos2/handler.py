"""run_chronos2 tool: invoke Plan A chronos2_client + return PathSet URI.

Inputs:
  {"panel_uri": str, "as_of": "YYYY-MM-DD", "horizon": int, "n_paths": int,
   "covariates_uri": str?, "conditioning": dict?}
Outputs: {"paths_uri": str, "n_paths": int, "horizon": int}

`simulate_chronos2` (Plan A) takes a `Chronos2Client` (wrapping a SageMaker
runtime client), slices the lookback window up to `as_of`, calls the endpoint,
and returns a fully-formed PathSet (source "chronos2" / "chronos2_conditional").
"""
from __future__ import annotations
import io
import os
import pickle
import uuid

import boto3

from chronos2_demo.models import chronos2_client
from tools.lambda_.shared import responses, s3_io
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
        panel = s3_io.download_parquet(event["panel_uri"])
        as_of = event["as_of"]
    except KeyError as e:
        return responses.error(f"missing input: {e}")

    covariates = None
    if event.get("covariates_uri"):
        covariates = s3_io.download_parquet(event["covariates_uri"])

    client = chronos2_client.Chronos2Client(
        endpoint_name=os.environ["CHRONOS2_ENDPOINT"],
        runtime=boto3.client("sagemaker-runtime"),
    )
    ps = chronos2_client.simulate_chronos2(
        client,
        panel=panel,
        as_of=as_of,
        horizon=horizon,
        n_paths=n_paths,
        covariates=covariates,
        conditioning=event.get("conditioning"),
    )

    bucket = os.environ["DATA_BUCKET"]
    sid = uuid.uuid4().hex[:12]
    key = f"sessions/{sid}/chronos2.pkl"
    buf = io.BytesIO()
    pickle.dump(ps, buf)
    boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    return responses.ok({
        "paths_uri": f"s3://{bucket}/{key}",
        "n_paths": n_paths,
        "horizon": horizon,
    })
