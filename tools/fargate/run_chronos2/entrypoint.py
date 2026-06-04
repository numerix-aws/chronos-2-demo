"""Fargate entrypoint for the run_chronos2 task.

Env vars:
  DATA_BUCKET, PANEL_URI, AS_OF, HORIZON, N_PATHS, OUTPUT_KEY,
  CHRONOS2_ENDPOINT, COVARIATES_URI?, SEED?
Output: S3 URI (pickle) of a PathSet.

Opens the AutoGluon Cloud endpoint (the single autogluon-cloud import lives in
`infra.sagemaker_endpoint.open_endpoint`), then runs Plan A's simulate_chronos2,
which reconstructs joint paths from the endpoint's per-series quantiles.
"""
from __future__ import annotations
import io
import os
import pickle
import sys

import boto3

from chronos2_demo.infra import sagemaker_endpoint
from chronos2_demo.models import chronos2_client
from tools.lambda_.shared import s3_io


def main() -> str:
    bucket = os.environ["DATA_BUCKET"]
    panel_uri = os.environ["PANEL_URI"]
    as_of = os.environ["AS_OF"]
    horizon = int(os.environ["HORIZON"])
    n_paths = int(os.environ["N_PATHS"])
    output_key = os.environ["OUTPUT_KEY"]
    endpoint_name = os.environ["CHRONOS2_ENDPOINT"]
    seed = int(os.environ.get("SEED", "0"))

    if horizon <= 0 or horizon > 1000:
        raise ValueError(f"HORIZON must be in (0, 1000], got {horizon}")
    if n_paths <= 0 or n_paths > 20_000:
        raise ValueError(f"N_PATHS must be in (0, 20000], got {n_paths}")

    panel = s3_io.download_parquet(panel_uri)
    covariates = None
    if os.environ.get("COVARIATES_URI"):
        covariates = s3_io.download_parquet(os.environ["COVARIATES_URI"])

    endpoint = sagemaker_endpoint.open_endpoint(endpoint_name)
    client = chronos2_client.Chronos2Client(endpoint=endpoint)
    ps = chronos2_client.simulate_chronos2(
        client,
        panel=panel,
        as_of=as_of,
        horizon=horizon,
        n_paths=n_paths,
        covariates=covariates,
        seed=seed,
    )

    buf = io.BytesIO()
    pickle.dump(ps, buf)
    boto3.client("s3").put_object(Bucket=bucket, Key=output_key, Body=buf.getvalue())
    uri = f"s3://{bucket}/{output_key}"
    print(uri, file=sys.stdout)
    return uri


if __name__ == "__main__":
    main()
