"""load_data tool: stage the manifest-owned aligned run inputs.

Inputs: {"session_id": str, "execution_id": str}
"""
from __future__ import annotations
import io
import os

import pandas as pd

from chronos2_demo.data.regimes import label_regimes, w_stress_series
from chronos2_demo.execution import aligned_run_inputs
from tools.lambda_.shared import responses, run_manifest, s3_io
from tools.lambda_.shared.bedrock import bedrock_action


def _verified_source(raw: bytes, expected_hash: str, name: str) -> pd.DataFrame:
    if s3_io.sha256_bytes(raw) != expected_hash:
        raise ValueError(f"{name} snapshot content hash mismatch")
    return pd.read_parquet(io.BytesIO(raw))


def _upload_frame(
    frame: pd.DataFrame,
    *,
    bucket: str,
    key: str,
    artifact_kind: str,
    spec,
) -> tuple[str, str]:
    buffer = io.BytesIO()
    frame.to_parquet(buffer)
    artifact_uri, artifact_sha256 = s3_io.upload_bytes(
        buffer.getvalue(),
        bucket=bucket,
        key=key,
        content_type="application/vnd.apache.parquet",
    )
    run_manifest.put_artifact_sidecar(
        artifact_uri=artifact_uri,
        artifact_sha256=artifact_sha256,
        artifact_kind=artifact_kind,
        spec=spec,
        producer_version=spec.provenance["tool_bundle_version"],
    )
    return artifact_uri, artifact_sha256


@bedrock_action
def handler(event: dict, _ctx) -> dict:
    try:
        event["session_id"]
        spec = run_manifest.load_run_spec(event["execution_id"])
        bucket = os.environ["DATA_BUCKET"]
        panel_raw = s3_io.download_bytes(f"s3://{bucket}/panel.parquet")
        covariates_raw = s3_io.download_bytes(f"s3://{bucket}/covariates.parquet")
        panel = _verified_source(
            panel_raw,
            spec.provenance["market_sha256"],
            "market",
        )
        covariates = _verified_source(
            covariates_raw,
            spec.provenance["covariate_sha256"],
            "covariate",
        )
        aligned = aligned_run_inputs(
            panel,
            covariates,
            as_of_date=spec.as_of_date,
            lookback_days=spec.lookback_days,
        )
        regimes = pd.concat(
            [
                w_stress_series(aligned.panel),
                label_regimes(aligned.panel, threshold=spec.regime_threshold),
            ],
            axis=1,
        )
        prefix = f"runs/{spec.execution_id}"
        panel_uri, panel_sha256 = _upload_frame(
            aligned.panel,
            bucket=bucket,
            key=f"{prefix}/panel.parquet",
            artifact_kind="market_panel",
            spec=spec,
        )
        covariates_uri, covariates_sha256 = _upload_frame(
            aligned.covariates,
            bucket=bucket,
            key=f"{prefix}/covariates.parquet",
            artifact_kind="covariates",
            spec=spec,
        )
        regimes_uri, regimes_sha256 = _upload_frame(
            regimes,
            bucket=bucket,
            key=f"{prefix}/regimes.parquet",
            artifact_kind="regimes",
            spec=spec,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return responses.error(str(exc))

    return responses.ok({
        "execution_id": spec.execution_id,
        "spec_hash": spec.spec_hash,
        "panel_uri": panel_uri,
        "panel_sha256": panel_sha256,
        "covariates_uri": covariates_uri,
        "covariates_sha256": covariates_sha256,
        "regimes_uri": regimes_uri,
        "regimes_sha256": regimes_sha256,
        "n_rows": int(len(aligned.panel)),
        "as_of_date": spec.as_of_date,
    })
