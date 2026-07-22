import hashlib
import io
import json

import numpy as np
import pandas as pd
import pytest

from chronos2_demo.data.regimes import label_regimes, w_stress_series
from chronos2_demo.execution import aligned_run_inputs
from chronos2_demo.run_spec import PROFILE, compute_spec_hash
from tools.lambda_.load_data import handler
from tools.lambda_.shared import s3_io


def _parquet_bytes(frame):
    buffer = io.BytesIO()
    frame.to_parquet(buffer)
    return buffer.getvalue()


def _seed_run(s3, bucket="test-data"):
    dates = pd.bdate_range("2022-01-03", periods=100)
    panel = pd.DataFrame(
        100.0 + np.arange(500, dtype=float).reshape(100, 5) / 100.0,
        index=dates,
        columns=["USDEUR", "USDJPY", "USD_2Y", "USD_5Y", "USD_10Y"],
    )
    covariates = pd.DataFrame(
        {
            "WTI": np.linspace(70.0, 80.0, len(dates)),
            "VIX": np.linspace(15.0, 25.0, len(dates)),
            "MOVE": np.linspace(80.0, 100.0, len(dates)),
        },
        index=dates,
    )
    panel_raw = _parquet_bytes(panel)
    covariates_raw = _parquet_bytes(covariates)
    as_of_date = dates[-10].strftime("%Y-%m-%d")
    provenance = {
        "market_snapshot_id": "market-v1",
        "market_sha256": hashlib.sha256(panel_raw).hexdigest(),
        "covariate_snapshot_id": "covariates-v1",
        "covariate_sha256": hashlib.sha256(covariates_raw).hexdigest(),
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
    payload = {
        **PROFILE,
        "as_of_date": as_of_date,
        "lookback_days": 60,
        "regime_threshold": 0.7,
        "provenance": provenance,
    }
    payload["spec_hash"] = compute_spec_hash(payload)
    payload["execution_id"] = "run-1"

    s3.put_object(Bucket=bucket, Key="panel.parquet", Body=panel_raw)
    s3.put_object(Bucket=bucket, Key="covariates.parquet", Body=covariates_raw)
    s3.put_object(Bucket=bucket, Key="regimes.parquet", Body=b"must-not-be-read")
    s3.put_object(
        Bucket=bucket,
        Key="runs/run-1/run_spec.json",
        Body=json.dumps(payload).encode("utf-8"),
    )
    return panel, covariates, panel_raw, covariates_raw, payload


def _body(s3, key):
    return s3.get_object(Bucket="test-data", Key=key)["Body"].read()


def _put_manifest(s3, payload):
    s3.put_object(
        Bucket="test-data",
        Key="runs/run-1/run_spec.json",
        Body=json.dumps(payload).encode("utf-8"),
    )


def test_load_data_stages_exact_manifest_aligned_inputs_and_sidecars(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    panel, covariates, panel_raw, covariates_raw, spec = _seed_run(s3)

    out = handler.handler(
        {"session_id": "session-1", "execution_id": "run-1"},
        None,
    )

    assert out["status"] == "ok"
    result = out["result"]
    assert result["execution_id"] == "run-1"
    assert result["spec_hash"] == spec["spec_hash"]
    assert result["panel_uri"] == "s3://test-data/runs/run-1/panel.parquet"
    assert result["covariates_uri"] == "s3://test-data/runs/run-1/covariates.parquet"
    assert result["regimes_uri"] == "s3://test-data/runs/run-1/regimes.parquet"
    assert result["n_rows"] == 60
    assert result["as_of_date"] == spec["as_of_date"]

    staged_panel = s3_io.download_parquet(result["panel_uri"])
    staged_covariates = s3_io.download_parquet(result["covariates_uri"])
    staged_regimes = s3_io.download_parquet(result["regimes_uri"])
    expected = aligned_run_inputs(
        panel,
        covariates,
        as_of_date=spec["as_of_date"],
        lookback_days=spec["lookback_days"],
    )
    expected_regimes = pd.concat(
        [
            w_stress_series(expected.panel),
            label_regimes(expected.panel, threshold=spec["regime_threshold"]),
        ],
        axis=1,
    )
    pd.testing.assert_frame_equal(staged_panel, expected.panel, check_freq=False)
    pd.testing.assert_frame_equal(staged_covariates, expected.covariates, check_freq=False)
    pd.testing.assert_frame_equal(staged_regimes, expected_regimes, check_freq=False)
    assert staged_panel.index.equals(staged_covariates.index)
    assert staged_panel.index.equals(staged_regimes.index)
    assert staged_panel.index[-1].strftime("%Y-%m-%d") == spec["as_of_date"]

    for name, kind in (
        ("panel", "market_panel"),
        ("covariates", "covariates"),
        ("regimes", "regimes"),
    ):
        raw = _body(s3, f"runs/run-1/{name}.parquet")
        assert result[f"{name}_sha256"] == s3_io.sha256_bytes(raw)
        meta = json.loads(_body(s3, f"runs/run-1/{name}.meta.json"))
        assert meta == {
            "artifact_kind": kind,
            "artifact_sha256": result[f"{name}_sha256"],
            "artifact_uri": result[f"{name}_uri"],
            "execution_id": "run-1",
            "producer_version": "git:test",
            "scenario_role": None,
            "source": None,
            "spec_hash": spec["spec_hash"],
        }

    assert _body(s3, "panel.parquet") == panel_raw
    assert _body(s3, "covariates.parquet") == covariates_raw
    assert _body(s3, "regimes.parquet") == b"must-not-be-read"


@pytest.mark.parametrize(
    "key,replacement,expected_message",
    [
        ("panel.parquet", b"tampered-panel", "market snapshot"),
        ("covariates.parquet", b"tampered-covariates", "covariate snapshot"),
    ],
)
def test_load_data_rejects_mutated_source_snapshot(
    s3, monkeypatch, key, replacement, expected_message
):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    _seed_run(s3)
    s3.put_object(Bucket="test-data", Key=key, Body=replacement)

    out = handler.handler(
        {"session_id": "session-1", "execution_id": "run-1"},
        None,
    )

    assert out["status"] == "error"
    assert expected_message in out["message"]
    assert s3.list_objects_v2(Bucket="test-data", Prefix="runs/run-1/panel.parquet").get(
        "KeyCount", 0
    ) == 0


def test_load_data_returns_validation_error_for_non_object_manifest(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    s3.put_object(
        Bucket="test-data",
        Key="runs/run-1/run_spec.json",
        Body=b"[]",
    )

    out = handler.handler(
        {"session_id": "session-1", "execution_id": "run-1"},
        None,
    )

    assert out["status"] == "error"
    assert out["message"].startswith("load_data validation failed:")
    assert "JSON object" in out["message"]


def test_load_data_returns_validation_error_for_missing_source_object(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    _seed_run(s3)
    s3.delete_object(Bucket="test-data", Key="panel.parquet")

    out = handler.handler(
        {"session_id": "session-1", "execution_id": "run-1"},
        None,
    )

    assert out["status"] == "error"
    assert out["message"].startswith("load_data validation failed:")
    assert "market snapshot unavailable at s3://test-data/panel.parquet" in out["message"]
    assert "NoSuchKey" in out["message"]


def test_load_data_returns_validation_error_for_unreadable_verified_parquet(
    s3, monkeypatch
):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    _, _, _, _, payload = _seed_run(s3)
    invalid = b"verified but not parquet"
    payload["provenance"]["market_sha256"] = hashlib.sha256(invalid).hexdigest()
    payload["spec_hash"] = compute_spec_hash(payload)
    s3.put_object(Bucket="test-data", Key="panel.parquet", Body=invalid)
    _put_manifest(s3, payload)

    out = handler.handler(
        {"session_id": "session-1", "execution_id": "run-1"},
        None,
    )

    assert out["status"] == "error"
    assert out["message"].startswith("load_data validation failed:")
    assert "market snapshot parquet decode failed" in out["message"]
    assert "Parquet" in out["message"]
