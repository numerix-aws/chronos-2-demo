"""Fargate entrypoint for the baseline MC task.

Env vars:
  DATA_BUCKET, EXECUTION_ID, SPEC_HASH, PANEL_URI, OUTPUT_URI, AS_OF, HORIZON,
  N_PATHS, N_COMPONENTS, SEED, PRODUCER_VERSION
Output: S3 URI (pickle) of a PathSet.

`simulate_baseline` (Plan A) fits PCA + factor dynamics on the panel history up
to `AS_OF` and returns a fully-formed PathSet (source="parametric"), so the
entrypoint just validates, runs, and uploads.
"""
from __future__ import annotations
import os
import pickle
import sys

from chronos2_demo.models import baseline_mc
from tools.lambda_.shared import run_manifest, s3_io


def main() -> str:
    spec = run_manifest.load_run_spec(os.environ["EXECUTION_ID"])
    if spec.spec_hash != os.environ["SPEC_HASH"]:
        raise ValueError("SPEC_HASH does not match RunSpec")
    panel_uri = os.environ["PANEL_URI"]
    as_of = os.environ["AS_OF"]
    horizon = int(os.environ["HORIZON"])
    n_paths = int(os.environ["N_PATHS"])
    n_components = int(os.environ["N_COMPONENTS"])
    output_uri = os.environ["OUTPUT_URI"]
    seed = int(os.environ["SEED"])

    if horizon <= 0 or horizon > 1000:
        raise ValueError(f"HORIZON must be in (0, 1000], got {horizon}")
    if n_paths <= 0 or n_paths > 50_000:
        raise ValueError(f"N_PATHS must be in (0, 50000], got {n_paths}")

    panel = s3_io.download_parquet(panel_uri)
    pathset = baseline_mc.simulate_baseline(
        panel=panel,
        as_of=as_of,
        horizon=horizon,
        n_paths=n_paths,
        n_components=n_components,
        seed=seed,
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
