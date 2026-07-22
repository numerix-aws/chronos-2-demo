import json

import pytest

from chronos2_demo.run_spec import (
    PROFILE,
    RunSpec,
    canonical_run_payload,
    compute_spec_hash,
)
from tools.lambda_.shared import s3_io
from tools.lambda_.shared.run_manifest import (
    load_run_spec,
    put_artifact_sidecar,
    run_spec_uri,
    sidecar_uri,
    validate_argument,
    validate_artifact,
)


PROVENANCE = {
    "market_snapshot_id": "market-v1",
    "market_sha256": "a" * 64,
    "covariate_snapshot_id": "covariates-v1",
    "covariate_sha256": "b" * 64,
    "chronos_endpoint": "chronos2-demo",
    "baseline_image_digest": "sha256:baseline",
    "chronos_image_digest": "sha256:chronos",
    "agent_image_digest": "sha256:agent",
    "book_version": "cross_asset_demo_v1",
    "blend_version": "importance_weight_v1",
    "pricing_version": "cross_asset_v1",
    "tool_bundle_version": "git:test",
    "strands_version": "1.30.0",
}


def _run_spec(execution_id="run-1"):
    payload = {**PROFILE, "provenance": PROVENANCE}
    return RunSpec(
        **payload,
        spec_hash=compute_spec_hash(payload),
        execution_id=execution_id,
    )


def _manifest_payload(spec):
    return {
        **spec.__dict__,
        "provenance": dict(spec.provenance),
        "conditioning": dict(spec.conditioning) if spec.conditioning else None,
    }


def _put_manifest(s3, spec, **updates):
    payload = {**_manifest_payload(spec), **updates}
    s3.put_object(
        Bucket="test-data",
        Key=f"runs/{spec.execution_id}/run_spec.json",
        Body=json.dumps(payload).encode("utf-8"),
    )


@pytest.fixture
def run_spec():
    return _run_spec()


def test_s3_byte_and_json_helpers_preserve_uploaded_bytes(s3):
    raw = b"\x00exact\xffbytes\n"
    uri, digest = s3_io.upload_bytes(
        raw,
        bucket="test-data",
        key="artifacts/value.bin",
        content_type="application/octet-stream",
    )

    assert uri == "s3://test-data/artifacts/value.bin"
    assert s3_io.download_bytes(uri) == raw
    assert digest == s3_io.sha256_bytes(raw)
    assert s3_io.split_s3_uri(uri) == ("test-data", "artifacts/value.bin")

    payload = {"z": 1, "a": "value"}
    json_uri, json_digest = s3_io.upload_json(
        payload,
        bucket="test-data",
        key="artifacts/value.json",
    )
    expected = b'{"a":"value","z":1}'
    assert s3_io.download_bytes(json_uri) == expected
    assert s3_io.download_json(json_uri) == payload
    assert json_digest == s3_io.sha256_bytes(expected)


@pytest.mark.parametrize("uri", ["https://bucket/key", "s3://", "s3://bucket", "s3:///key"])
def test_split_s3_uri_rejects_invalid_uri(uri):
    with pytest.raises(ValueError, match="s3 URI"):
        s3_io.split_s3_uri(uri)


def test_load_run_spec_uses_canonical_key_and_validates_identity(s3, monkeypatch, run_spec):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    _put_manifest(s3, run_spec)

    loaded = load_run_spec("run-1")

    assert run_spec_uri("run-1") == "s3://test-data/runs/run-1/run_spec.json"
    assert loaded.execution_id == run_spec.execution_id
    assert loaded.spec_hash == run_spec.spec_hash
    assert loaded.provenance == run_spec.provenance


def test_load_run_spec_deeply_freezes_nested_mappings_without_changing_hash(
    s3, monkeypatch
):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    payload = {
        **PROFILE,
        "conditioning": {
            "series_shifts": {"EUR_2Y": -0.5, "EUR_5Y": -0.5},
            "n_anchor_days": 30,
        },
        "provenance": PROVENANCE,
    }
    spec = RunSpec(
        **payload,
        spec_hash=compute_spec_hash(payload),
        execution_id="run-1",
    )
    _put_manifest(s3, spec)

    loaded = load_run_spec("run-1")

    with pytest.raises(TypeError):
        loaded.provenance["market_snapshot_id"] = "mutated"
    with pytest.raises(TypeError):
        loaded.conditioning["n_anchor_days"] = 10
    with pytest.raises(TypeError):
        loaded.conditioning["series_shifts"]["EUR_2Y"] = 0.0
    assert canonical_run_payload(loaded) == canonical_run_payload(spec)
    assert compute_spec_hash(canonical_run_payload(loaded)) == spec.spec_hash


def test_load_run_spec_rejects_non_object_json(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    s3.put_object(
        Bucket="test-data",
        Key="runs/run-1/run_spec.json",
        Body=b"[]",
    )

    with pytest.raises(ValueError, match="JSON object"):
        load_run_spec("run-1")


def test_load_run_spec_rejects_missing_or_unexpected_fields(s3, monkeypatch, run_spec):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    _put_manifest(s3, run_spec, unexpected="value")

    with pytest.raises(ValueError, match="unexpected fields"):
        load_run_spec("run-1")

    payload = _manifest_payload(run_spec)
    payload.pop("horizon")
    s3.put_object(
        Bucket="test-data",
        Key="runs/run-1/run_spec.json",
        Body=json.dumps(payload).encode("utf-8"),
    )
    with pytest.raises(ValueError, match="missing fields"):
        load_run_spec("run-1")


def test_load_run_spec_rejects_tampered_manifest(s3, monkeypatch, run_spec):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    _put_manifest(s3, run_spec, spec_hash="bad")

    with pytest.raises(ValueError, match="spec_hash"):
        load_run_spec("run-1")


def test_load_run_spec_rejects_internal_execution_id_mismatch(s3, monkeypatch, run_spec):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    _put_manifest(s3, run_spec, execution_id="run-2")

    with pytest.raises(ValueError, match="execution_id"):
        load_run_spec("run-1")


def test_validate_argument_rejects_model_override(run_spec):
    with pytest.raises(ValueError, match="horizon disagrees"):
        validate_argument(run_spec, "horizon", 365)


def test_validate_artifact_checks_sidecar_identity_source_and_exact_content(
    s3, monkeypatch, run_spec
):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    raw = b"serialized-pathset"
    artifact_uri, artifact_sha256 = s3_io.upload_bytes(
        raw,
        bucket="test-data",
        key="runs/run-1/baseline.pkl",
        content_type="application/octet-stream",
    )
    meta = put_artifact_sidecar(
        artifact_uri=artifact_uri,
        artifact_sha256=artifact_sha256,
        artifact_kind="pathset",
        spec=run_spec,
        producer_version="sha256:baseline",
        source="parametric",
    )

    assert meta.scenario_role == "baseline"
    assert validate_artifact(
        artifact_uri,
        spec=run_spec,
        allowed_kinds={"pathset"},
        allowed_sources={"parametric"},
    ) == meta

    with pytest.raises(ValueError, match="PathSet source"):
        validate_artifact(
            artifact_uri,
            spec=run_spec,
            allowed_kinds={"pathset"},
            allowed_sources={"chronos2"},
        )

    s3.put_object(
        Bucket="test-data",
        Key="runs/run-1/baseline.pkl",
        Body=b"tampered-pathset",
    )
    with pytest.raises(ValueError, match="content hash"):
        validate_artifact(
            artifact_uri,
            spec=run_spec,
            allowed_kinds={"pathset"},
            allowed_sources={"parametric"},
        )


def test_validate_artifact_rejects_sidecar_from_another_execution(
    s3, monkeypatch, run_spec
):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    artifact_uri, artifact_sha256 = s3_io.upload_bytes(
        b"serialized-pathset",
        bucket="test-data",
        key="runs/run-1/baseline.pkl",
        content_type="application/octet-stream",
    )
    put_artifact_sidecar(
        artifact_uri=artifact_uri,
        artifact_sha256=artifact_sha256,
        artifact_kind="pathset",
        spec=_run_spec("run-2"),
        producer_version="sha256:baseline",
        source="parametric",
    )

    with pytest.raises(ValueError, match="run identity"):
        validate_artifact(
            artifact_uri,
            spec=run_spec,
            allowed_kinds={"pathset"},
        )


@pytest.mark.parametrize(
    "artifact_uri,expected",
    [
        ("s3://bucket/foo.pkl", "s3://bucket/foo.meta.json"),
        ("s3://bucket/foo", "s3://bucket/foo.meta.json"),
        (
            "s3://bucket.with.dots/dir.with.dots/foo.pkl",
            "s3://bucket.with.dots/dir.with.dots/foo.meta.json",
        ),
        (
            "s3://bucket.with.dots/dir.with.dots/foo",
            "s3://bucket.with.dots/dir.with.dots/foo.meta.json",
        ),
    ],
)
def test_sidecar_uri_replaces_only_artifact_basename_extension(artifact_uri, expected):
    assert sidecar_uri(artifact_uri) == expected


@pytest.mark.parametrize(
    "bucket,key,error",
    [
        ("test-plots", "runs/run-1/baseline.pkl", "DATA_BUCKET"),
        ("test-data", "archive/runs/run-1/baseline.pkl", "run prefix"),
        ("test-data", "runs/run-10/baseline.pkl", "run prefix"),
    ],
)
def test_validate_artifact_rejects_cross_bucket_or_cross_prefix(
    s3, monkeypatch, run_spec, bucket, key, error
):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    artifact_uri, artifact_sha256 = s3_io.upload_bytes(
        b"serialized-pathset",
        bucket=bucket,
        key=key,
        content_type="application/octet-stream",
    )
    put_artifact_sidecar(
        artifact_uri=artifact_uri,
        artifact_sha256=artifact_sha256,
        artifact_kind="pathset",
        spec=run_spec,
        producer_version="sha256:baseline",
        source="parametric",
    )

    with pytest.raises(ValueError, match=error):
        validate_artifact(
            artifact_uri,
            spec=run_spec,
            allowed_kinds={"pathset"},
            allowed_sources={"parametric"},
        )


@pytest.mark.parametrize(
    "source,bad_role",
    [("parametric", "augmented"), (None, "baseline")],
)
def test_validate_artifact_rejects_mismatched_scenario_role(
    s3, monkeypatch, run_spec, source, bad_role
):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    artifact_uri, artifact_sha256 = s3_io.upload_bytes(
        b"serialized-artifact",
        bucket="test-data",
        key="runs/run-1/artifact.pkl",
        content_type="application/octet-stream",
    )
    meta = put_artifact_sidecar(
        artifact_uri=artifact_uri,
        artifact_sha256=artifact_sha256,
        artifact_kind="pathset" if source else "market_panel",
        spec=run_spec,
        producer_version="git:test",
        source=source,
    )
    payload = {**meta.__dict__, "scenario_role": bad_role}
    bucket, key = s3_io.split_s3_uri(sidecar_uri(artifact_uri))
    s3_io.upload_json(payload, bucket=bucket, key=key)

    with pytest.raises(ValueError, match="scenario_role"):
        validate_artifact(
            artifact_uri,
            spec=run_spec,
            allowed_kinds={"pathset", "market_panel"},
            allowed_sources={"parametric"} if source else None,
        )
