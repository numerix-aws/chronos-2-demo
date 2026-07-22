import json
import pickle

import numpy as np
import pandas as pd
import pytest

from chronos2_demo.pricing.book import DEFAULT_BOOK_PATH
from chronos2_demo.run_spec import PROFILE, RunSpec, compute_spec_hash
from chronos2_demo.types import PathSet
from tools.lambda_.price_book import handler
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
SERIES = [
    "USDEUR", "USDJPY", "USDGBP", "USD_5Y", "EUR_5Y", "JPY_5Y", "GBP_5Y",
    "SPX", "NIKKEI225", "US_IG_OAS", "US_HY_OAS",
]


def _put_run(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("BOOK_PATH", str(DEFAULT_BOOK_PATH))
    payload = {
        **PROFILE,
        "as_of_date": "2022-06-30",
        "horizon": 3,
        "n_paths": 4,
        "provenance": PROVENANCE,
    }
    spec = RunSpec(
        **payload,
        spec_hash=compute_spec_hash(payload),
        execution_id="run-1",
    )
    manifest = {
        **spec.__dict__,
        "provenance": dict(spec.provenance),
        "conditioning": None,
    }
    s3.put_object(
        Bucket="test-data",
        Key="runs/run-1/run_spec.json",
        Body=json.dumps(manifest).encode(),
    )
    return spec


def _put_pathset(s3, spec, name, source, *, value=1.0, sidecar_source=None):
    paths = PathSet(
        paths=np.full((4, spec.horizon, len(SERIES)), value),
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
    meta_source = sidecar_source or source
    producer = {
        "parametric": spec.provenance["baseline_image_digest"],
        "chronos2": spec.provenance["chronos_image_digest"],
        "chronos2_conditional": spec.provenance["chronos_image_digest"],
        "blended": spec.provenance["blend_version"],
    }[meta_source]
    run_manifest.put_artifact_sidecar(
        artifact_uri=uri,
        artifact_sha256=digest,
        artifact_kind="pathset",
        source=meta_source,
        spec=spec,
        producer_version=producer,
    )
    return uri


def _metrics(paths):
    values = np.arange(paths.horizon, dtype=float)
    return {
        "ee": values,
        "pfe_975": values + 1.0,
        "es_975": values + 2.0,
        "dates": paths.dates,
    }


def _result(out):
    assert out["status"] == "ok", out
    return out["result"]


def test_price_book_reverse_order_uses_pathset_source_for_roles(s3, monkeypatch):
    spec = _put_run(s3, monkeypatch)
    baseline_uri = _put_pathset(s3, spec, "baseline", "parametric")
    chronos_uri = _put_pathset(s3, spec, "chronos2", "chronos2")
    augmented_uri = _put_pathset(s3, spec, "blended", "blended")
    monkeypatch.setattr(handler.exposure, "compute_metrics", lambda _swaps, paths, **_k: _metrics(paths))

    chronos = _result(handler.handler({"execution_id": "run-1", "paths_uri": chronos_uri}, None))
    augmented = _result(handler.handler({"execution_id": "run-1", "paths_uri": augmented_uri}, None))
    baseline = _result(handler.handler({"execution_id": "run-1", "paths_uri": baseline_uri}, None))

    assert baseline["scenario_role"] == "baseline"
    assert chronos["scenario_role"] == "chronos_only"
    assert augmented["scenario_role"] == "augmented"
    assert baseline["source"] == "parametric"
    assert baseline["execution_id"] == spec.execution_id
    assert baseline["spec_hash"] == spec.spec_hash
    assert baseline["paths_uri"] == baseline_uri
    assert baseline["paths_sha256"] == s3_io.sha256_bytes(s3_io.download_bytes(baseline_uri))
    assert baseline["metrics_uri"] == "s3://test-data/runs/run-1/metrics/baseline.json"
    assert baseline["metrics_sha256"] == s3_io.sha256_bytes(
        s3_io.download_bytes(baseline["metrics_uri"])
    )
    assert baseline["terminal"] == {
        "date": "2022-07-05",
        "ee": 2.0,
        "pfe_975": 3.0,
        "es_975": 4.0,
    }
    assert all(isinstance(value, float) for value in baseline["ee"])
    meta = s3_io.download_json(run_manifest.sidecar_uri(baseline["metrics_uri"]))
    assert meta["source"] == "parametric"
    assert meta["scenario_role"] == "baseline"
    assert meta["producer_version"] == spec.provenance["pricing_version"]


def test_price_book_prices_the_full_cross_asset_book(s3, monkeypatch):
    spec = _put_run(s3, monkeypatch)
    uri = _put_pathset(s3, spec, "baseline", "parametric")
    book = (["swap"], ["equity"], ["credit"])
    monkeypatch.setattr(handler.book_mod, "load_cross_asset_book", lambda _path: book)
    monkeypatch.setattr(
        handler.book_mod,
        "load_book",
        lambda _path: pytest.fail("swap-only load_book must not be called"),
    )

    def compute_metrics(swaps, paths, *, q=None, equity_forwards, cds_protection):
        assert swaps == book[0]
        assert equity_forwards == book[1]
        assert cds_protection == book[2]
        assert q == 0.975
        return _metrics(paths)

    monkeypatch.setattr(handler.exposure, "compute_metrics", compute_metrics)

    _result(handler.handler({"execution_id": "run-1", "paths_uri": uri}, None))


def test_price_book_allows_identical_retry_but_prevents_role_overwrite(s3, monkeypatch):
    spec = _put_run(s3, monkeypatch)
    chronos_uri = _put_pathset(s3, spec, "chronos2", "chronos2", value=1.0)
    monkeypatch.setattr(handler.exposure, "compute_metrics", lambda _swaps, paths, **_k: _metrics(paths))

    first = _result(handler.handler({"execution_id": "run-1", "paths_uri": chronos_uri}, None))
    first_bytes = s3_io.download_bytes(first["metrics_uri"])
    retry = _result(handler.handler({"execution_id": "run-1", "paths_uri": chronos_uri}, None))
    assert retry["metrics_sha256"] == first["metrics_sha256"]
    assert s3_io.download_bytes(first["metrics_uri"]) == first_bytes

    conflicting_payload = s3_io.download_json(first["metrics_uri"])
    conflicting_payload["source"] = "chronos2_conditional"
    with pytest.raises(ValueError, match="different bytes|overwrite"):
        handler._put_metrics(
            conflicting_payload,
            spec=spec,
            source="chronos2_conditional",
            role="chronos_only",
        )
    assert s3_io.download_bytes(first["metrics_uri"]) == first_bytes


@pytest.mark.parametrize("source", ["parametric", "chronos2", "blended"])
def test_price_book_rejects_alias_path_key_with_valid_identity(
    s3, monkeypatch, source
):
    spec = _put_run(s3, monkeypatch)
    uri = _put_pathset(s3, spec, f"{source}-alias", source)
    monkeypatch.setattr(
        handler.exposure,
        "compute_metrics",
        lambda _swaps, paths, **_kwargs: _metrics(paths),
    )

    out = handler.handler({"execution_id": "run-1", "paths_uri": uri}, None)

    assert out["status"] == "error"
    assert "key" in out["message"].lower() or "exact" in out["message"].lower()


def test_price_metrics_retry_rejects_sequential_byte_conflict(s3, monkeypatch):
    spec = _put_run(s3, monkeypatch)
    uri = _put_pathset(s3, spec, "baseline", "parametric")
    monkeypatch.setattr(
        handler.exposure,
        "compute_metrics",
        lambda _swaps, paths, **_kwargs: _metrics(paths),
    )
    first = _result(handler.handler({"execution_id": "run-1", "paths_uri": uri}, None))
    bucket, key = s3_io.split_s3_uri(first["metrics_uri"])
    s3.put_object(Bucket=bucket, Key=key, Body=b"conflicting-winner")

    retry = handler.handler({"execution_id": "run-1", "paths_uri": uri}, None)

    assert retry["status"] == "error"
    assert "different bytes" in retry["message"] or "overwrite" in retry["message"]
    assert s3_io.download_bytes(first["metrics_uri"]) == b"conflicting-winner"


def test_price_book_rejects_pathset_source_sidecar_mismatch(s3, monkeypatch):
    spec = _put_run(s3, monkeypatch)
    uri = _put_pathset(
        s3,
        spec,
        "baseline",
        "parametric",
        sidecar_source="chronos2",
    )

    out = handler.handler({"execution_id": "run-1", "paths_uri": uri}, None)

    assert out["status"] == "error"
    assert "source" in out["message"].lower()


def test_price_book_rejects_forged_producer_version(s3, monkeypatch):
    spec = _put_run(s3, monkeypatch)
    uri = _put_pathset(s3, spec, "baseline", "parametric")
    meta_uri = run_manifest.sidecar_uri(uri)
    meta = s3_io.download_json(meta_uri)
    meta["producer_version"] = "sha256:forged"
    bucket, key = s3_io.split_s3_uri(meta_uri)
    s3_io.upload_json(meta, bucket=bucket, key=key)

    out = handler.handler({"execution_id": "run-1", "paths_uri": uri}, None)

    assert out["status"] == "error"
    assert "producer" in out["message"]


def test_price_metrics_serializer_rejects_non_finite_numbers():
    with pytest.raises(ValueError, match="range"):
        handler._json_bytes({"pfe_975": float("nan")})
