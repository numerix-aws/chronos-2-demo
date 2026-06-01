import io
import numpy as np
import pandas as pd
import pickle
import pytest
from tools.lambda_.price_book import handler
from chronos2_demo.pricing.book import DEFAULT_BOOK_PATH
from chronos2_demo.types import PathSet


def _seed_pathset(s3_client, bucket, key):
    rng = np.random.default_rng(0)
    n_paths, horizon = 200, 21
    # Series the demo book values against (EUR/JPY/GBP legs + USD rate tenors).
    series = ["USDEUR", "USDJPY", "USDGBP", "USD_5Y", "EUR_5Y", "JPY_5Y", "GBP_5Y"]
    ps = PathSet(
        paths=rng.normal(1.0, 0.02, size=(n_paths, horizon, len(series))),
        weights=np.full(n_paths, 1.0 / n_paths),
        series=series,
        dates=pd.bdate_range("2022-07-01", periods=horizon),
        source="parametric",
    )
    buf = io.BytesIO()
    pickle.dump(ps, buf)
    s3_client.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    return f"s3://{bucket}/{key}"


def test_price_book_returns_metric_summary(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("BOOK_PATH", str(DEFAULT_BOOK_PATH))
    uri = _seed_pathset(s3, "test-data", "ps.pkl")
    out = handler.handler({"paths_uri": uri, "book_id": "demo"}, None)
    assert out["status"] == "ok"
    r = out["result"]
    for k in ("ee", "pfe_975", "es_975", "dates", "metrics_uri"):
        assert k in r
    assert len(r["ee"]) == len(r["dates"]) == 21
    assert r["metrics_uri"].startswith("s3://test-data/")


def test_price_book_rejects_unknown_book(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("BOOK_PATH", str(DEFAULT_BOOK_PATH))
    uri = _seed_pathset(s3, "test-data", "ps.pkl")
    out = handler.handler({"paths_uri": uri, "book_id": "unknown"}, None)
    assert out["status"] == "error"
