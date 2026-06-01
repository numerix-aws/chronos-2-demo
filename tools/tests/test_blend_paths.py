import io
import numpy as np
import pandas as pd
import pickle
import pytest
from tools.lambda_.blend_paths import handler
from chronos2_demo.pricing.book import DEFAULT_BOOK_PATH
from chronos2_demo.types import PathSet

# Series the demo book values against (EUR/JPY/GBP legs + USD rate tenors).
SERIES = ["USDEUR", "USDJPY", "USDGBP", "USD_5Y", "EUR_5Y", "JPY_5Y", "GBP_5Y"]


def _seed_pathset(s3_client, bucket, key, n_paths=100, horizon=21, seed=0):
    rng = np.random.default_rng(seed)
    ps = PathSet(
        paths=rng.normal(1.0, 0.02, size=(n_paths, horizon, len(SERIES))),
        weights=np.full(n_paths, 1.0 / n_paths),
        series=SERIES,
        dates=pd.bdate_range("2022-07-01", periods=horizon),
        source="parametric",
    )
    buf = io.BytesIO()
    pickle.dump(ps, buf)
    s3_client.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    return f"s3://{bucket}/{key}"


def test_blend_paths_returns_blended_uri(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("BOOK_PATH", str(DEFAULT_BOOK_PATH))
    para_uri = _seed_pathset(s3, "test-data", "para.pkl", seed=0)
    chr_uri = _seed_pathset(s3, "test-data", "chr.pkl", seed=1)
    out = handler.handler(
        {"parametric_uri": para_uri, "chronos2_uri": chr_uri, "w_stress": 0.7},
        None,
    )
    assert out["status"] == "ok"
    assert out["result"]["blended_uri"].startswith("s3://test-data/")
    assert 0.0 <= out["result"]["w_stress"] <= 1.0


def test_blend_paths_rejects_w_stress_out_of_range(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("BOOK_PATH", str(DEFAULT_BOOK_PATH))
    para_uri = _seed_pathset(s3, "test-data", "p.pkl")
    chr_uri = _seed_pathset(s3, "test-data", "c.pkl")
    out = handler.handler(
        {"parametric_uri": para_uri, "chronos2_uri": chr_uri, "w_stress": 1.5},
        None,
    )
    assert out["status"] == "error"
    assert "w_stress" in out["message"]
