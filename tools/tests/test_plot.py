import io
import json
import pickle

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

from chronos2_demo.run_spec import PROFILE, RunSpec, compute_spec_hash
from chronos2_demo.types import PathSet
from tools.lambda_.plot import handler
from tools.lambda_.shared import run_manifest, s3_io


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


def _put_run(s3, monkeypatch, execution_id="run-1"):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("PLOTS_BUCKET", "test-plots")
    payload = {
        **PROFILE,
        "as_of_date": "2022-06-30",
        "horizon": 3,
        "n_paths": 4,
        "regime_threshold": 0.6,
        "provenance": PROVENANCE,
    }
    spec = RunSpec(
        **payload,
        spec_hash=compute_spec_hash(payload),
        execution_id=execution_id,
    )
    manifest = {
        **spec.__dict__,
        "provenance": dict(spec.provenance),
        "conditioning": None,
    }
    s3.put_object(
        Bucket="test-data",
        Key=f"runs/{execution_id}/run_spec.json",
        Body=json.dumps(manifest).encode(),
    )
    return spec


def _put_pathset(s3, spec, name, source):
    paths = PathSet(
        paths=np.ones((4, spec.horizon, 1)),
        weights=np.full(4, 0.25),
        series=["USDEUR"],
        dates=pd.bdate_range("2022-07-01", periods=spec.horizon),
        source=source,
    )
    raw = pickle.dumps(paths, protocol=pickle.HIGHEST_PROTOCOL)
    uri, digest = s3_io.upload_bytes(
        raw,
        bucket="test-data",
        key=f"runs/{spec.execution_id}/{name}.pkl",
        content_type="application/octet-stream",
    )
    producer = {
        "parametric": spec.provenance["baseline_image_digest"],
        "chronos2": spec.provenance["chronos_image_digest"],
        "blended": spec.provenance["blend_version"],
    }[source]
    run_manifest.put_artifact_sidecar(
        artifact_uri=uri,
        artifact_sha256=digest,
        artifact_kind="pathset",
        source=source,
        spec=spec,
        producer_version=producer,
    )
    return uri, digest


def _put_metrics(s3, spec, name, source, role, *, payload_updates=None):
    path_name = {
        "parametric": "baseline",
        "chronos2": "chronos2",
        "blended": "blended",
    }[source]
    paths_uri, paths_sha256 = _put_pathset(s3, spec, path_name, source)
    payload = {
        "execution_id": spec.execution_id,
        "spec_hash": spec.spec_hash,
        "scenario_role": role,
        "source": source,
        "paths_uri": paths_uri,
        "paths_sha256": paths_sha256,
        "ee": [0.0, 0.1, 0.2],
        "pfe_975": [0.0, 0.5, 1.0],
        "es_975": [0.0, 0.6, 1.2],
        "dates": ["2022-07-01", "2022-07-04", "2022-07-05"],
        "terminal": {
            "date": "2022-07-05",
            "ee": 0.2,
            "pfe_975": 1.0,
            "es_975": 1.2,
        },
    }
    payload.update(payload_updates or {})
    uri, digest = s3_io.upload_json(
        payload,
        bucket="test-data",
        key=f"runs/{spec.execution_id}/metrics/{name}.json",
    )
    run_manifest.put_artifact_sidecar(
        artifact_uri=uri,
        artifact_sha256=digest,
        artifact_kind="metrics",
        source=source,
        spec=spec,
        producer_version=spec.provenance["pricing_version"],
    )
    return uri


def _result(out):
    assert out["status"] == "ok", out
    return out["result"]


def _put_regimes(s3, spec, name="regimes"):
    regimes = pd.DataFrame(
        {"w_stress": [0.2, 0.8, 0.4], "regime": ["calm", "stress", "calm"]},
        index=pd.bdate_range("2022-06-28", periods=3),
    )
    buffer = io.BytesIO()
    regimes.to_parquet(buffer)
    uri, digest = s3_io.upload_bytes(
        buffer.getvalue(),
        bucket="test-data",
        key=f"runs/{spec.execution_id}/{name}.parquet",
        content_type="application/vnd.apache.parquet",
    )
    run_manifest.put_artifact_sidecar(
        artifact_uri=uri,
        artifact_sha256=digest,
        artifact_kind="regimes",
        spec=spec,
        producer_version=spec.provenance["tool_bundle_version"],
    )
    return regimes, uri


def test_pfe_overlay_derives_roles_in_either_uri_order_and_publishes_identity(
    s3, monkeypatch
):
    spec = _put_run(s3, monkeypatch)
    baseline_uri = _put_metrics(s3, spec, "baseline", "parametric", "baseline")
    augmented_uri = _put_metrics(s3, spec, "augmented", "blended", "augmented")
    rendered = {}

    def render(*, baseline, augmented, title):
        rendered.update(
            baseline=baseline["scenario_role"],
            augmented=augmented["scenario_role"],
            title=title,
        )
        return plt.subplots()[0]

    monkeypatch.setattr(handler.pfe_overlay, "plot_pfe_overlay", render)
    result = _result(handler.handler({
        "execution_id": "run-1",
        "spec": "pfe_overlay",
        "baseline_uri": augmented_uri,
        "augmented_uri": baseline_uri,
        "title": "model-generated title must not define identity",
    }, None))

    assert rendered == {
        "baseline": "baseline",
        "augmented": "augmented",
        "title": "PFE overlay",
    }
    assert result["execution_id"] == spec.execution_id
    assert result["spec_hash"] == spec.spec_hash
    assert result["plot_role"] == "pfe_overlay"
    assert result["image_s3_uri"] == "s3://test-plots/runs/run-1/plots/pfe_overlay.png"
    assert result["image_uri"].startswith("https://")
    image_bytes = s3_io.download_bytes(result["image_s3_uri"])
    assert image_bytes.startswith(b"\x89PNG")
    assert result["image_sha256"] == s3_io.sha256_bytes(image_bytes)
    meta = s3_io.download_json(run_manifest.sidecar_uri(result["image_s3_uri"]))
    assert meta["artifact_kind"] == "plot"
    assert meta["producer_version"] == spec.provenance["tool_bundle_version"]
    assert meta["artifact_sha256"] == result["image_sha256"]
    assert run_manifest.validate_artifact(
        result["image_s3_uri"],
        spec=spec,
        allowed_kinds={"plot"},
        expected_bucket="test-plots",
        expected_key="runs/run-1/plots/pfe_overlay.png",
        expected_uri=result["image_s3_uri"],
    ).artifact_sha256 == result["image_sha256"]


@pytest.mark.parametrize(
    "second_source,second_role",
    [("parametric", "baseline"), ("chronos2", "chronos_only")],
)
def test_pfe_overlay_requires_exactly_baseline_and_augmented(
    s3, monkeypatch, second_source, second_role
):
    spec = _put_run(s3, monkeypatch)
    baseline_uri = _put_metrics(s3, spec, "baseline", "parametric", "baseline")
    other_uri = _put_metrics(s3, spec, "other", second_source, second_role)

    out = handler.handler({
        "execution_id": "run-1",
        "spec": "pfe_overlay",
        "baseline_uri": baseline_uri,
        "augmented_uri": other_uri,
    }, None)

    assert out["status"] == "error"
    assert (
        "baseline" in out["message"] and "augmented" in out["message"]
    ) or "exact" in out["message"]


def test_pfe_overlay_rejects_alias_metrics_key_with_valid_identity(s3, monkeypatch):
    spec = _put_run(s3, monkeypatch)
    baseline_uri = _put_metrics(
        s3, spec, "baseline-alias", "parametric", "baseline"
    )
    augmented_uri = _put_metrics(s3, spec, "augmented", "blended", "augmented")

    out = handler.handler({
        "execution_id": "run-1",
        "spec": "pfe_overlay",
        "baseline_uri": baseline_uri,
        "augmented_uri": augmented_uri,
    }, None)

    assert out["status"] == "error"
    assert "key" in out["message"].lower() or "exact" in out["message"].lower()


def test_pfe_overlay_rejects_cross_run_artifact(s3, monkeypatch):
    spec = _put_run(s3, monkeypatch)
    other_spec = _put_run(s3, monkeypatch, execution_id="run-2")
    baseline_uri = _put_metrics(s3, spec, "baseline", "parametric", "baseline")
    augmented_uri = _put_metrics(s3, other_spec, "augmented", "blended", "augmented")

    out = handler.handler({
        "execution_id": "run-1",
        "spec": "pfe_overlay",
        "baseline_uri": baseline_uri,
        "augmented_uri": augmented_uri,
    }, None)

    assert out["status"] == "error"


@pytest.mark.parametrize("tamper", ["artifact_hash", "content_source", "paths_hash"])
def test_pfe_overlay_rejects_hash_content_and_source_mismatches(s3, monkeypatch, tamper):
    spec = _put_run(s3, monkeypatch)
    baseline_uri = _put_metrics(s3, spec, "baseline", "parametric", "baseline")
    augmented_uri = _put_metrics(s3, spec, "augmented", "blended", "augmented")
    if tamper == "artifact_hash":
        bucket, key = s3_io.split_s3_uri(augmented_uri)
        payload = s3_io.download_json(augmented_uri)
        payload["pfe_975"][-1] = 99.0
        s3_io.upload_json(payload, bucket=bucket, key=key)
    else:
        payload = s3_io.download_json(augmented_uri)
        if tamper == "content_source":
            payload["source"] = "parametric"
        else:
            payload["paths_sha256"] = "f" * 64
        bucket, key = s3_io.split_s3_uri(augmented_uri)
        _, digest = s3_io.upload_json(payload, bucket=bucket, key=key)
        meta_uri = run_manifest.sidecar_uri(augmented_uri)
        meta = s3_io.download_json(meta_uri)
        meta["artifact_sha256"] = digest
        meta_bucket, meta_key = s3_io.split_s3_uri(meta_uri)
        s3_io.upload_json(meta, bucket=meta_bucket, key=meta_key)

    out = handler.handler({
        "execution_id": "run-1",
        "spec": "pfe_overlay",
        "baseline_uri": baseline_uri,
        "augmented_uri": augmented_uri,
    }, None)

    assert out["status"] == "error"


def test_regime_ribbon_validates_staged_identity_and_manifest_threshold(s3, monkeypatch):
    spec = _put_run(s3, monkeypatch)
    regimes, uri = _put_regimes(s3, spec)
    rendered = {}

    def render(values, *, threshold, title):
        rendered.update(values=values.copy(), threshold=threshold, title=title)
        return plt.subplots()[0]

    monkeypatch.setattr(handler.regime_ribbon, "plot_regime_ribbon", render)
    result = _result(handler.handler({
        "execution_id": "run-1",
        "spec": "regime_ribbon",
        "regimes_uri": uri,
        "threshold": 0.1,
        "title": "ignore me",
    }, None))

    assert rendered["threshold"] == spec.regime_threshold
    assert rendered["title"] == "Regime ribbon"
    pd.testing.assert_series_equal(
        rendered["values"], regimes["w_stress"], check_freq=False
    )
    assert result["plot_role"] == "regime_ribbon"
    assert result["image_s3_uri"] == "s3://test-plots/runs/run-1/plots/regime_ribbon.png"


def test_regime_ribbon_rejects_alias_staged_key(s3, monkeypatch):
    spec = _put_run(s3, monkeypatch)
    _, uri = _put_regimes(s3, spec, name="regimes-alias")

    out = handler.handler({
        "execution_id": "run-1",
        "spec": "regime_ribbon",
        "regimes_uri": uri,
    }, None)

    assert out["status"] == "error"
    assert "key" in out["message"].lower() or "exact" in out["message"].lower()


def test_path_fan_rejects_alias_path_key(s3, monkeypatch):
    spec = _put_run(s3, monkeypatch)
    uri, _ = _put_pathset(s3, spec, "baseline-alias", "parametric")

    out = handler.handler({
        "execution_id": "run-1",
        "spec": "path_fan",
        "paths_uri": uri,
        "series": "USDEUR",
    }, None)

    assert out["status"] == "error"
    assert "key" in out["message"].lower() or "exact" in out["message"].lower()


def test_path_fan_malformed_pickle_returns_error_envelope(s3, monkeypatch):
    spec = _put_run(s3, monkeypatch)
    uri, _ = _put_pathset(s3, spec, "baseline", "parametric")
    bucket, key = s3_io.split_s3_uri(uri)
    raw = b"not-a-pickle"
    s3.put_object(Bucket=bucket, Key=key, Body=raw)
    meta_uri = run_manifest.sidecar_uri(uri)
    meta = s3_io.download_json(meta_uri)
    meta["artifact_sha256"] = s3_io.sha256_bytes(raw)
    meta_bucket, meta_key = s3_io.split_s3_uri(meta_uri)
    s3_io.upload_json(meta, bucket=meta_bucket, key=meta_key)

    out = handler.handler({
        "execution_id": "run-1",
        "spec": "path_fan",
        "paths_uri": uri,
        "series": "USDEUR",
    }, None)

    assert out["status"] == "error"
    assert "decode" in out["message"].lower() or "pickle" in out["message"].lower()


def test_plot_closes_figure_when_png_rendering_fails(s3, monkeypatch):
    spec = _put_run(s3, monkeypatch)
    _, uri = _put_regimes(s3, spec)
    fig = plt.subplots()[0]
    monkeypatch.setattr(
        handler.regime_ribbon,
        "plot_regime_ribbon",
        lambda *_args, **_kwargs: fig,
    )
    monkeypatch.setattr(
        handler,
        "_fig_to_png",
        lambda _fig: (_ for _ in ()).throw(ValueError("render failed")),
    )

    out = handler.handler({
        "execution_id": "run-1",
        "spec": "regime_ribbon",
        "regimes_uri": uri,
    }, None)

    assert out["status"] == "error"
    assert not plt.fignum_exists(fig.number)


def test_plot_png_retry_rejects_sequential_byte_conflict(s3, monkeypatch):
    spec = _put_run(s3, monkeypatch)
    _, uri = _put_regimes(s3, spec)
    event = {
        "execution_id": "run-1",
        "spec": "regime_ribbon",
        "regimes_uri": uri,
    }
    first = _result(handler.handler(event, None))
    bucket, key = s3_io.split_s3_uri(first["image_s3_uri"])
    s3.put_object(Bucket=bucket, Key=key, Body=b"conflicting-winner")

    retry = handler.handler(event, None)

    assert retry["status"] == "error"
    assert "different bytes" in retry["message"]
    assert s3_io.download_bytes(first["image_s3_uri"]) == b"conflicting-winner"


def test_publish_keeps_chart_url_valid_for_one_hour(monkeypatch):
    monkeypatch.setenv("PLOTS_BUCKET", "test-plots")
    captured = {}
    validated = {}

    def upload(_data, *, bucket, key, expires_in):
        captured.update(bucket=bucket, key=key, expires_in=expires_in)
        return "https://example.com/chart.png"

    monkeypatch.setattr(handler.s3_io, "upload_png_signed", upload)
    run_manifest_module = getattr(handler, "run_manifest", type("RunManifest", (), {})())
    monkeypatch.setattr(handler, "run_manifest", run_manifest_module, raising=False)
    monkeypatch.setattr(
        run_manifest_module,
        "put_artifact_sidecar",
        lambda **_kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(
        run_manifest_module,
        "validate_artifact",
        lambda uri, **kwargs: validated.update(uri=uri, **kwargs)
        or type("Meta", (), {"producer_version": "git:test"})(),
        raising=False,
    )
    spec = type("Spec", (), {
        "execution_id": "run-1",
        "spec_hash": "c" * 64,
        "provenance": {"tool_bundle_version": "git:test"},
    })()

    result = handler._publish(b"png", spec=spec, plot_role="pfe_overlay")

    assert result["image_uri"] == "https://example.com/chart.png"
    assert captured == {
        "bucket": "test-plots",
        "key": "runs/run-1/plots/pfe_overlay.png",
        "expires_in": 3600,
    }
    assert validated["expected_bucket"] == "test-plots"
    assert validated["expected_key"] == "runs/run-1/plots/pfe_overlay.png"


def test_plot_rejects_unknown_spec(s3, monkeypatch):
    _put_run(s3, monkeypatch)
    out = handler.handler({"execution_id": "run-1", "spec": "nope"}, None)
    assert out["status"] == "error"
