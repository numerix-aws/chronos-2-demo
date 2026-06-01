import json
import numpy as np
import pandas as pd
import pytest
from tools.lambda_.load_data import handler


def _seed_panel(s3, bucket="test-data"):
    """Seed the bucket with a panel + regime labels."""
    dates = pd.bdate_range("2022-01-03", periods=200)
    panel = pd.DataFrame(
        np.random.default_rng(0).normal(0, 0.005, size=(200, 5)).cumsum(axis=0),
        index=dates,
        columns=["USDEUR", "USDJPY", "USD_2Y", "USD_5Y", "USD_10Y"],
    )
    labels = pd.Series(np.zeros(200), index=dates, name="w_stress")
    from tools.lambda_.shared import s3_io
    s3_io.upload_parquet(panel, bucket=bucket, key="panel.parquet")
    s3_io.upload_parquet(labels.to_frame(), bucket=bucket, key="regimes.parquet")


def test_load_data_returns_s3_uri_for_lookback_slice(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    _seed_panel(s3)
    event = {"as_of_date": "2022-06-30", "lookback_days": 60}
    out = handler.handler(event, None)
    assert out["status"] == "ok"
    assert out["result"]["panel_uri"].startswith("s3://test-data/")
    assert out["result"]["regimes_uri"].startswith("s3://test-data/")
    assert out["result"]["n_rows"] == 60


def test_load_data_rejects_bad_date(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    _seed_panel(s3)
    out = handler.handler({"as_of_date": "not-a-date", "lookback_days": 60}, None)
    assert out["status"] == "error"
    assert "as_of_date" in out["message"]


def test_load_data_rejects_lookback_outside_panel(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    _seed_panel(s3)
    out = handler.handler({"as_of_date": "2010-01-01", "lookback_days": 60}, None)
    assert out["status"] == "error"
