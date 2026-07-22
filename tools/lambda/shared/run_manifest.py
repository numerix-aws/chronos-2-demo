from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
import os
import posixpath
from types import MappingProxyType

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


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def load_run_spec(execution_id: str) -> RunSpec:
    payload = s3_io.download_json(run_spec_uri(execution_id))
    if not isinstance(payload, dict):
        raise ValueError("run manifest must be a JSON object")
    expected_fields = {field.name for field in fields(RunSpec)}
    missing = sorted(expected_fields - payload.keys())
    unexpected = sorted(payload.keys() - expected_fields)
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing fields: {missing}")
        if unexpected:
            details.append(f"unexpected fields: {unexpected}")
        raise ValueError(f"run manifest shape mismatch ({'; '.join(details)})")
    if not isinstance(payload["provenance"], dict):
        raise ValueError("run manifest provenance must be a JSON object")
    if payload["conditioning"] is not None and not isinstance(
        payload["conditioning"], dict
    ):
        raise ValueError("run manifest conditioning must be a JSON object or null")
    if payload.get("execution_id") != execution_id:
        raise ValueError("run manifest execution_id mismatch")
    expected = compute_spec_hash(payload)
    if payload.get("spec_hash") != expected:
        raise ValueError("run manifest spec_hash mismatch")
    frozen = {
        **payload,
        "provenance": _freeze(payload["provenance"]),
        "conditioning": _freeze(payload["conditioning"]),
    }
    return RunSpec(**frozen)


def validate_argument(spec: RunSpec, name: str, supplied: object) -> None:
    expected = getattr(spec, name)
    if supplied != expected:
        raise ValueError(
            f"{name} disagrees with RunSpec: supplied={supplied!r}, expected={expected!r}"
        )


def sidecar_uri(artifact_uri: str) -> str:
    bucket, key = s3_io.split_s3_uri(artifact_uri)
    directory, separator, basename = key.rpartition("/")
    if not basename:
        raise ValueError(f"artifact URI must name an object: {artifact_uri!r}")
    stem, extension = posixpath.splitext(basename)
    sidecar_name = f"{stem if extension else basename}.meta.json"
    sidecar_key = f"{directory}/{sidecar_name}" if separator else sidecar_name
    return f"s3://{bucket}/{sidecar_key}"


def put_artifact_sidecar(
    *,
    artifact_uri: str,
    artifact_sha256: str,
    artifact_kind: str,
    spec: RunSpec,
    producer_version: str,
    source: str | None = None,
) -> ArtifactMeta:
    actual_hash = s3_io.sha256_bytes(s3_io.download_bytes(artifact_uri))
    if actual_hash != artifact_sha256:
        raise ValueError("artifact content hash does not match sidecar claim")
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
    s3_io.create_or_verify_bytes(
        s3_io.json_bytes(meta.__dict__),
        bucket=bucket,
        key=key,
        content_type="application/json",
    )
    return meta


def validate_artifact(
    artifact_uri: str,
    *,
    spec: RunSpec,
    allowed_kinds: set[str],
    allowed_sources: set[str] | None = None,
    expected_bucket: str | None = None,
    expected_key: str | None = None,
    expected_uri: str | None = None,
) -> ArtifactMeta:
    bucket, key = s3_io.split_s3_uri(artifact_uri)
    trusted_bucket = expected_bucket or os.environ["DATA_BUCKET"]
    if bucket != trusted_bucket:
        label = "expected bucket" if expected_bucket else "configured DATA_BUCKET"
        raise ValueError(f"artifact bucket does not match {label}")
    if expected_key is not None and key != expected_key:
        raise ValueError("artifact key does not match exact expected key")
    if expected_uri is not None and artifact_uri != expected_uri:
        raise ValueError("artifact URI does not match exact expected URI")
    run_prefix = f"runs/{spec.execution_id}/"
    if not key.startswith(run_prefix):
        raise ValueError(f"artifact key does not match run prefix {run_prefix!r}")
    payload = s3_io.download_json(sidecar_uri(artifact_uri))
    meta = ArtifactMeta(**payload)
    if meta.execution_id != spec.execution_id or meta.spec_hash != spec.spec_hash:
        raise ValueError("artifact run identity mismatch")
    if meta.artifact_uri != artifact_uri or meta.artifact_kind not in allowed_kinds:
        raise ValueError("artifact source identity mismatch")
    if allowed_sources is not None and meta.source not in allowed_sources:
        raise ValueError("artifact PathSet source mismatch")
    expected_role = scenario_role(meta.source) if meta.source is not None else None
    if meta.scenario_role != expected_role:
        raise ValueError("artifact scenario_role does not match source")
    actual_hash = s3_io.sha256_bytes(s3_io.download_bytes(artifact_uri))
    if actual_hash != meta.artifact_sha256:
        raise ValueError("artifact content hash mismatch")
    return meta
