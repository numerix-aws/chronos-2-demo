import io
import json
import pickle

import numpy as np
import pandas as pd
import pytest

from chronos2_demo.pricing.book import DEFAULT_BOOK_PATH
from chronos2_demo.run_spec import PROFILE, RunSpec, compute_spec_hash
from chronos2_demo.types import PathSet
from tools.lambda_.blend_paths import handler
from tools.lambda_.shared import run_manifest, s3_io


PROVENANCE = {
    "market_snapshot_id": "market-v1",
    "market_sha256": "",
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
SERIES = ["USDEUR", "USD_5Y"]


def _put_run(s3, monkeypatch, *, horizon=3, future_rows=None, conditioning=None):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("BOOK_PATH", str(DEFAULT_BOOK_PATH))
    dates = pd.bdate_range("2022-06-29", periods=2 + (future_rows or horizon))
    panel = pd.DataFrame(
        np.arange(len(dates) * len(SERIES), dtype=float).reshape(len(dates), -1) + 1.0,
        index=dates,
        columns=SERIES,
    )
    raw = io.BytesIO()
    panel.to_parquet(raw)
    panel_bytes = raw.getvalue()
    s3.put_object(Bucket="test-data", Key="panel.parquet", Body=panel_bytes)
    provenance = {**PROVENANCE, "market_sha256": s3_io.sha256_bytes(panel_bytes)}
    payload = {
        **PROFILE,
        "as_of_date": "2022-06-30",
        "lookback_days": 2,
        "horizon": horizon,
        "n_paths": 4,
        "w_stress": 0.65,
        "regime_threshold": 0.6,
        "conditioning": conditioning,
        "provenance": provenance,
    }
    spec = RunSpec(
        **payload,
        spec_hash=compute_spec_hash(payload),
        execution_id="run-1",
    )
    manifest = {
        **spec.__dict__,
        "provenance": dict(spec.provenance),
        "conditioning": conditioning,
    }
    s3.put_object(
        Bucket="test-data",
        Key="runs/run-1/run_spec.json",
        Body=json.dumps(manifest).encode(),
    )
    return spec


def _put_pathset(s3, spec, name, source, *, producer=None):
    rng = np.random.default_rng(0 if source == "parametric" else 1)
    paths = PathSet(
        paths=rng.normal(1.0, 0.02, size=(4, spec.horizon, len(SERIES))),
        weights=np.full(4, 0.25),
        series=SERIES,
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
    run_manifest.put_artifact_sidecar(
        artifact_uri=uri,
        artifact_sha256=digest,
        artifact_kind="pathset",
        source=source,
        spec=spec,
        producer_version=producer or (
            spec.provenance["baseline_image_digest"]
            if source == "parametric"
            else spec.provenance["chronos_image_digest"]
        ),
    )
    return uri


def _body(out):
    assert out["status"] == "ok", out
    return out["result"]


def _stub_pricing(monkeypatch):
    book = (["swap"], ["equity"], ["credit"])
    monkeypatch.setattr(handler.book_mod, "load_cross_asset_book", lambda _path: book)
    monkeypatch.setattr(
        handler.book_mod,
        "load_book",
        lambda _path: pytest.fail("swap-only load_book must not be called"),
    )

    def portfolio_mtm(_swaps, paths, *, equity_forwards, cds_protection):
        assert equity_forwards == book[1]
        assert cds_protection == book[2]
        return np.arange(paths.n_paths * paths.horizon, dtype=float).reshape(
            paths.n_paths, paths.horizon
        )

    monkeypatch.setattr(handler.exposure, "portfolio_mtm", portfolio_mtm)
    return book


def _stub_diagnostics(monkeypatch):
    monkeypatch.setattr(
        handler.run_evaluation,
        "compute_attribution",
        lambda *_a, **_k: {},
    )
    monkeypatch.setattr(
        handler.run_evaluation,
        "compute_portfolio_coverage",
        lambda *_a, **_k: {"available": True},
    )
    monkeypatch.setattr(
        handler.run_evaluation,
        "compute_factor_coverage",
        lambda *_a, **_k: {"available": True},
    )


def test_blend_uses_manifest_identity_and_writes_diagnostics(s3, monkeypatch):
    spec = _put_run(s3, monkeypatch)
    parametric_uri = _put_pathset(s3, spec, "baseline", "parametric")
    chronos_uri = _put_pathset(s3, spec, "chronos2", "chronos2")
    book = _stub_pricing(monkeypatch)
    calls = {}

    def attribution(actual_book, parametric, chronos, *, w_stress):
        calls["attribution"] = (actual_book, parametric.source, chronos.source, w_stress)
        return {"final_blend": {"terminal": {"pfe_975": 1.0}}}

    def portfolio_coverage(actual_book, distributions, future):
        calls["portfolio"] = (actual_book, tuple(distributions), future.copy())
        return {"available": True, "nominal": 0.975}

    def factor_coverage(distributions, future, regimes, *, regime_threshold):
        calls["factor"] = (tuple(distributions), future.copy(), regimes.copy(), regime_threshold)
        return {"available": True, "nominal": 0.95}

    run_evaluation = getattr(handler, "run_evaluation", type("RunEvaluation", (), {})())
    monkeypatch.setattr(handler, "run_evaluation", run_evaluation, raising=False)
    monkeypatch.setattr(run_evaluation, "compute_attribution", attribution, raising=False)
    monkeypatch.setattr(run_evaluation, "compute_portfolio_coverage", portfolio_coverage, raising=False)
    monkeypatch.setattr(run_evaluation, "compute_factor_coverage", factor_coverage, raising=False)

    result = _body(handler.handler({
        "execution_id": "run-1",
        "parametric_uri": parametric_uri,
        "chronos2_uri": chronos_uri,
        "w_stress": 0.2,
    }, None))

    assert result["execution_id"] == "run-1"
    assert result["spec_hash"] == spec.spec_hash
    assert result["blended_uri"] == "s3://test-data/runs/run-1/blended.pkl"
    assert result["diagnostics_uri"] == "s3://test-data/runs/run-1/diagnostics.json"
    assert result["w_stress"] == spec.w_stress
    assert calls["attribution"] == (book, "parametric", "chronos2", spec.w_stress)
    assert calls["portfolio"][1] == ("baseline", "chronos_only", "augmented")
    assert len(calls["portfolio"][2]) == spec.horizon
    assert calls["factor"][3] == spec.regime_threshold

    blended_raw = s3_io.download_bytes(result["blended_uri"])
    assert result["blended_sha256"] == s3_io.sha256_bytes(blended_raw)
    blended = pickle.loads(blended_raw)
    assert blended.source == "blended"
    blended_meta = s3_io.download_json(run_manifest.sidecar_uri(result["blended_uri"]))
    assert blended_meta["source"] == "blended"
    assert blended_meta["scenario_role"] == "augmented"
    assert blended_meta["producer_version"] == spec.provenance["blend_version"]

    diagnostics_raw = s3_io.download_bytes(result["diagnostics_uri"])
    assert result["diagnostics_sha256"] == s3_io.sha256_bytes(diagnostics_raw)
    diagnostics = json.loads(diagnostics_raw)
    assert diagnostics["execution_id"] == spec.execution_id
    assert diagnostics["spec_hash"] == spec.spec_hash
    assert diagnostics["provenance"] == {"book_version": "cross_asset_demo_v1"}
    assert diagnostics["portfolio_coverage"]["available"] is True


def test_blend_marks_incomplete_held_out_horizon_unavailable(s3, monkeypatch):
    spec = _put_run(s3, monkeypatch, horizon=4, future_rows=3)
    parametric_uri = _put_pathset(s3, spec, "baseline", "parametric")
    chronos_uri = _put_pathset(s3, spec, "chronos2", "chronos2")
    _stub_pricing(monkeypatch)
    run_evaluation = getattr(handler, "run_evaluation", type("RunEvaluation", (), {})())
    monkeypatch.setattr(handler, "run_evaluation", run_evaluation, raising=False)
    monkeypatch.setattr(
        run_evaluation,
        "compute_attribution",
        lambda *_a, **_k: {},
        raising=False,
    )

    result = _body(handler.handler({
        "execution_id": "run-1",
        "parametric_uri": parametric_uri,
        "chronos2_uri": chronos_uri,
        "w_stress": 0.2,
    }, None))

    assert result["diagnostics"]["portfolio_coverage"]["available"] is False
    assert result["diagnostics"]["factor_coverage"]["available"] is False
    assert "3 of 4" in result["diagnostics"]["portfolio_coverage"]["reason"]


@pytest.mark.parametrize(
    "conditioning,chronos_source",
    [
        (None, "chronos2_conditional"),
        (
            {"series_shifts": {"USD_5Y": -0.25}, "n_anchor_days": 1},
            "chronos2",
        ),
    ],
)
def test_blend_rejects_chronos_source_conditioning_mismatch(
    s3, monkeypatch, conditioning, chronos_source
):
    spec = _put_run(s3, monkeypatch, conditioning=conditioning)
    parametric_uri = _put_pathset(s3, spec, "baseline", "parametric")
    chronos_uri = _put_pathset(s3, spec, "chronos2", chronos_source)
    _stub_pricing(monkeypatch)
    _stub_diagnostics(monkeypatch)

    out = handler.handler({
        "execution_id": "run-1",
        "parametric_uri": parametric_uri,
        "chronos2_uri": chronos_uri,
    }, None)

    assert out["status"] == "error"
    assert "source" in out["message"].lower() or "conditioning" in out["message"].lower()


@pytest.mark.parametrize("engine", ["baseline", "chronos2"])
def test_blend_rejects_alias_engine_key_with_valid_identity(s3, monkeypatch, engine):
    spec = _put_run(s3, monkeypatch)
    parametric_uri = _put_pathset(
        s3,
        spec,
        "baseline-alias" if engine == "baseline" else "baseline",
        "parametric",
    )
    chronos_uri = _put_pathset(
        s3,
        spec,
        "chronos2-alias" if engine == "chronos2" else "chronos2",
        "chronos2",
    )
    _stub_pricing(monkeypatch)
    _stub_diagnostics(monkeypatch)

    out = handler.handler({
        "execution_id": "run-1",
        "parametric_uri": parametric_uri,
        "chronos2_uri": chronos_uri,
    }, None)

    assert out["status"] == "error"
    assert "key" in out["message"].lower() or "exact" in out["message"].lower()


@pytest.mark.parametrize("artifact", ["blended.pkl", "diagnostics.json"])
def test_blend_deterministic_outputs_reject_sequential_conflicts(
    s3, monkeypatch, artifact
):
    spec = _put_run(s3, monkeypatch)
    parametric_uri = _put_pathset(s3, spec, "baseline", "parametric")
    chronos_uri = _put_pathset(s3, spec, "chronos2", "chronos2")
    _stub_pricing(monkeypatch)
    _stub_diagnostics(monkeypatch)
    event = {
        "execution_id": "run-1",
        "parametric_uri": parametric_uri,
        "chronos2_uri": chronos_uri,
    }
    first = _body(handler.handler(event, None))
    target_uri = (
        first["blended_uri"] if artifact == "blended.pkl" else first["diagnostics_uri"]
    )
    bucket, key = s3_io.split_s3_uri(target_uri)
    s3.put_object(Bucket=bucket, Key=key, Body=b"conflicting-winner")

    retry = handler.handler(event, None)

    assert retry["status"] == "error"
    assert "different bytes" in retry["message"]
    assert s3_io.download_bytes(target_uri) == b"conflicting-winner"


def test_blend_rejects_non_finite_diagnostics_json(s3, monkeypatch):
    spec = _put_run(s3, monkeypatch)
    parametric_uri = _put_pathset(s3, spec, "baseline", "parametric")
    chronos_uri = _put_pathset(s3, spec, "chronos2", "chronos2")
    _stub_pricing(monkeypatch)
    monkeypatch.setattr(
        handler.run_evaluation,
        "compute_attribution",
        lambda *_a, **_k: {"terminal": {"pfe_975": float("nan")}},
    )
    monkeypatch.setattr(
        handler.run_evaluation,
        "compute_portfolio_coverage",
        lambda *_a, **_k: {"available": True},
    )
    monkeypatch.setattr(
        handler.run_evaluation,
        "compute_factor_coverage",
        lambda *_a, **_k: {"available": True},
    )

    out = handler.handler({
        "execution_id": "run-1",
        "parametric_uri": parametric_uri,
        "chronos2_uri": chronos_uri,
    }, None)

    assert out["status"] == "error"
    assert "JSON" in out["message"] or "range" in out["message"]


@pytest.mark.parametrize("tamper", ["producer", "source", "hash", "spec_hash", "execution"])
def test_blend_rejects_invalid_engine_identity(s3, monkeypatch, tamper):
    spec = _put_run(s3, monkeypatch)
    parametric_uri = _put_pathset(s3, spec, "baseline", "parametric")
    chronos_uri = _put_pathset(s3, spec, "chronos2", "chronos2")
    _stub_pricing(monkeypatch)
    meta_uri = run_manifest.sidecar_uri(parametric_uri)
    meta = s3_io.download_json(meta_uri)
    if tamper == "producer":
        meta["producer_version"] = "sha256:forged"
    elif tamper == "source":
        meta["source"] = "chronos2"
        meta["scenario_role"] = "chronos_only"
    elif tamper == "hash":
        s3.put_object(
            Bucket="test-data",
            Key="runs/run-1/baseline.pkl",
            Body=s3_io.download_bytes(chronos_uri),
        )
    elif tamper == "spec_hash":
        meta["spec_hash"] = "f" * 64
    else:
        meta["execution_id"] = "run-2"
    if tamper != "hash":
        bucket, key = s3_io.split_s3_uri(meta_uri)
        s3_io.upload_json(meta, bucket=bucket, key=key)

    out = handler.handler({
        "execution_id": "run-1",
        "parametric_uri": parametric_uri,
        "chronos2_uri": chronos_uri,
        "w_stress": 0.2,
    }, None)

    assert out["status"] == "error"


def test_blend_rejects_unauthorized_book_identity(s3, monkeypatch):
    spec = _put_run(s3, monkeypatch)
    manifest_uri = run_manifest.run_spec_uri(spec.execution_id)
    manifest = s3_io.download_json(manifest_uri)
    manifest["book_id"] = "other-book"
    manifest["spec_hash"] = compute_spec_hash(manifest)
    bucket, key = s3_io.split_s3_uri(manifest_uri)
    s3_io.upload_json(manifest, bucket=bucket, key=key)
    parametric_uri = _put_pathset(s3, spec, "baseline", "parametric")
    chronos_uri = _put_pathset(s3, spec, "chronos2", "chronos2")
    _stub_pricing(monkeypatch)

    out = handler.handler({
        "execution_id": "run-1",
        "parametric_uri": parametric_uri,
        "chronos2_uri": chronos_uri,
        "w_stress": 0.2,
    }, None)

    assert out["status"] == "error"
    assert "book" in out["message"]
