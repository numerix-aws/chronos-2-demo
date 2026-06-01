import io
import numpy as np
import pandas as pd
import pickle
import pytest
from tools.lambda_.plot import handler
from chronos2_demo.types import PathSet


def _seed_metrics(s3_client, bucket, key):
    metrics = {
        "ee": [0.0, 0.1, 0.2],
        "pfe_975": [0.0, 0.5, 1.0],
        "es_975": [0.0, 0.6, 1.2],
        "dates": ["2022-07-01", "2022-07-04", "2022-07-05"],
    }
    import json
    s3_client.put_object(
        Bucket=bucket, Key=key, Body=json.dumps(metrics).encode()
    )
    return f"s3://{bucket}/{key}"


def _seed_pathset(s3_client, bucket, key):
    rng = np.random.default_rng(0)
    ps = PathSet(
        paths=rng.normal(1.0, 0.05, size=(50, 10, 2)),
        weights=np.full(50, 1.0 / 50),
        series=["S0", "S1"],
        dates=pd.bdate_range("2022-07-01", periods=10),
        source="parametric",
    )
    buf = io.BytesIO()
    pickle.dump(ps, buf)
    s3_client.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    return f"s3://{bucket}/{key}"


def test_plot_pfe_overlay_returns_signed_uri(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("PLOTS_BUCKET", "test-plots")
    base = _seed_metrics(s3, "test-data", "b.json")
    aug = _seed_metrics(s3, "test-data", "a.json")
    out = handler.handler(
        {"spec": "pfe_overlay", "baseline_uri": base, "augmented_uri": aug,
         "title": "Test"},
        None,
    )
    assert out["status"] == "ok"
    assert out["result"]["image_uri"].startswith("https://")


def test_plot_rejects_unknown_spec(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("PLOTS_BUCKET", "test-plots")
    out = handler.handler({"spec": "nope"}, None)
    assert out["status"] == "error"
