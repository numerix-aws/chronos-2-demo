"""Fargate entrypoint for the baseline MC task.

Env vars:
  DATA_BUCKET, PANEL_URI, AS_OF, HORIZON, N_PATHS, N_COMPONENTS, OUTPUT_KEY, SEED
Output: S3 URI (pickle) of a PathSet.

`simulate_baseline` (Plan A) fits PCA + factor dynamics on the panel history up
to `AS_OF` and returns a fully-formed PathSet (source="parametric"), so the
entrypoint just validates, runs, and uploads.
"""
from __future__ import annotations
import io
import os
import pickle
import sys

import boto3

from chronos2_demo.models import baseline_mc
from tools.lambda_.shared import s3_io


def main() -> str:
    bucket = os.environ["DATA_BUCKET"]
    panel_uri = os.environ["PANEL_URI"]
    as_of = os.environ["AS_OF"]
    horizon = int(os.environ["HORIZON"])
    n_paths = int(os.environ["N_PATHS"])
    n_components = int(os.environ.get("N_COMPONENTS", "3"))
    output_key = os.environ["OUTPUT_KEY"]
    seed = int(os.environ.get("SEED", "0"))

    if horizon <= 0 or horizon > 1000:
        raise ValueError(f"HORIZON must be in (0, 1000], got {horizon}")
    if n_paths <= 0 or n_paths > 50_000:
        raise ValueError(f"N_PATHS must be in (0, 50000], got {n_paths}")

    panel = s3_io.download_parquet(panel_uri)
    ps = baseline_mc.simulate_baseline(
        panel=panel,
        as_of=as_of,
        horizon=horizon,
        n_paths=n_paths,
        n_components=n_components,
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
