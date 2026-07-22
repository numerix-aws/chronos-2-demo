"""Fargate entrypoint for the run_chronos2 task.

Env vars:
  DATA_BUCKET, EXECUTION_ID, SPEC_HASH, PANEL_URI, COVARIATES_URI, OUTPUT_URI,
  AS_OF, CHRONOS2_ENDPOINT, CONDITIONING_JSON, HORIZON, LOOKBACK_DAYS,
  N_PATHS, SEED, PRODUCER_VERSION
Output: S3 URI (pickle) of a PathSet.

Opens the AutoGluon Cloud endpoint (the single autogluon-cloud import lives in
`infra.sagemaker_endpoint.open_endpoint`), then runs Plan A's simulate_chronos2,
which reconstructs joint paths from the endpoint's per-series quantiles.
"""
from __future__ import annotations
import json
import os
import pickle
import sys

from chronos2_demo.infra import sagemaker_endpoint
from chronos2_demo.models import chronos2_client
from tools.lambda_.shared import run_manifest, s3_io


def main() -> str:
    spec = run_manifest.load_run_spec(os.environ["EXECUTION_ID"])
    if spec.spec_hash != os.environ["SPEC_HASH"]:
        raise ValueError("SPEC_HASH does not match RunSpec")
    panel_uri = os.environ["PANEL_URI"]
    output_uri = os.environ["OUTPUT_URI"]
    horizon = int(os.environ["HORIZON"])
    n_paths = int(os.environ["N_PATHS"])

    if horizon <= 0 or horizon > 1000:
        raise ValueError(f"HORIZON must be in (0, 1000], got {horizon}")
    if n_paths <= 0 or n_paths > 20_000:
        raise ValueError(f"N_PATHS must be in (0, 20000], got {n_paths}")

    panel = s3_io.download_parquet(panel_uri)
    covariates = s3_io.download_parquet(os.environ["COVARIATES_URI"])

    conditioning = None
    if os.environ.get("CONDITIONING_JSON"):
        payload = json.loads(os.environ["CONDITIONING_JSON"])
        conditioning = chronos2_client.Conditioning(
            series_shifts={
                key: float(value)
                for key, value in payload["series_shifts"].items()
            },
            n_anchor_days=int(payload["n_anchor_days"]),
        )

    endpoint = sagemaker_endpoint.open_endpoint(os.environ["CHRONOS2_ENDPOINT"])
    client = chronos2_client.Chronos2Client(endpoint=endpoint)
    pathset = chronos2_client.simulate_chronos2(
        client,
        panel=panel,
        as_of=os.environ["AS_OF"],
        covariates=covariates,
        horizon=horizon,
        n_paths=n_paths,
        lookback_days=int(os.environ["LOOKBACK_DAYS"]),
        conditioning=conditioning,
        seed=int(os.environ["SEED"]),
    )

    raw = pickle.dumps(pathset, protocol=pickle.HIGHEST_PROTOCOL)
    output_bucket, output_key = s3_io.split_s3_uri(output_uri)
    uploaded_uri, output_sha256 = s3_io.upload_bytes(
        raw,
        bucket=output_bucket,
        key=output_key,
        content_type="application/octet-stream",
    )
    run_manifest.put_artifact_sidecar(
        artifact_uri=uploaded_uri,
        artifact_sha256=output_sha256,
        artifact_kind="pathset",
        source=pathset.source,
        spec=spec,
        producer_version=os.environ["PRODUCER_VERSION"],
    )
    print(uploaded_uri, file=sys.stdout)
    return uploaded_uri


if __name__ == "__main__":
    main()
