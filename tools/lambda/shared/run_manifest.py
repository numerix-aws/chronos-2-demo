from __future__ import annotations

from dataclasses import dataclass
import os

from chronos2_demo.execution import scenario_role
from chronos2_demo.run_spec import RunSpec, compute_spec_hash
from tools.lambda_.shared import s3_io


@dataclass(frozen=True)
class ArtifactMeta:
    execution_id: str
    spec_hash: str
    artifact_uri: str
    artifact_sha256: str
    artifact_kind: str
    source: str | None
    scenario_role: str | None
    producer_version: str


def run_spec_uri(execution_id: str) -> str:
    return f"s3://{os.environ['DATA_BUCKET']}/runs/{execution_id}/run_spec.json"


def load_run_spec(execution_id: str) -> RunSpec:
    payload = s3_io.download_json(run_spec_uri(execution_id))
    if payload.get("execution_id") != execution_id:
        raise ValueError("run manifest execution_id mismatch")
    expected = compute_spec_hash(payload)
    if payload.get("spec_hash") != expected:
        raise ValueError("run manifest spec_hash mismatch")
    return RunSpec(**payload)


def validate_argument(spec: RunSpec, name: str, supplied: object) -> None:
    expected = getattr(spec, name)
    if supplied != expected:
        raise ValueError(
            f"{name} disagrees with RunSpec: supplied={supplied!r}, expected={expected!r}"
        )


def sidecar_uri(artifact_uri: str) -> str:
    suffix = artifact_uri.rsplit(".", 1)[0]
    return f"{suffix}.meta.json"


def put_artifact_sidecar(
    *,
    artifact_uri: str,
    artifact_sha256: str,
    artifact_kind: str,
    spec: RunSpec,
    producer_version: str,
    source: str | None = None,
) -> ArtifactMeta:
    meta = ArtifactMeta(
        execution_id=spec.execution_id,
        spec_hash=spec.spec_hash,
        artifact_uri=artifact_uri,
        artifact_sha256=artifact_sha256,
        artifact_kind=artifact_kind,
        source=source,
        scenario_role=scenario_role(source) if source is not None else None,
        producer_version=producer_version,
    )
    bucket, key = s3_io.split_s3_uri(sidecar_uri(artifact_uri))
    s3_io.upload_json(meta.__dict__, bucket=bucket, key=key)
    return meta


def validate_artifact(
    artifact_uri: str,
    *,
    spec: RunSpec,
    allowed_kinds: set[str],
    allowed_sources: set[str] | None = None,
) -> ArtifactMeta:
    payload = s3_io.download_json(sidecar_uri(artifact_uri))
    meta = ArtifactMeta(**payload)
    if meta.execution_id != spec.execution_id or meta.spec_hash != spec.spec_hash:
        raise ValueError("artifact run identity mismatch")
    if meta.artifact_uri != artifact_uri or meta.artifact_kind not in allowed_kinds:
        raise ValueError("artifact source identity mismatch")
    if allowed_sources is not None and meta.source not in allowed_sources:
        raise ValueError("artifact PathSet source mismatch")
    actual_hash = s3_io.sha256_bytes(s3_io.download_bytes(artifact_uri))
    if actual_hash != meta.artifact_sha256:
        raise ValueError("artifact content hash mismatch")
    return meta
