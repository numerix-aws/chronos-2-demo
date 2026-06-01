import io
import numpy as np
import pandas as pd
import pickle
import pytest
from unittest.mock import patch
from tools.lambda_.run_chronos2 import handler
from chronos2_demo.types import PathSet


def _seed_panel(s3_client, bucket="test-data"):
    from tools.lambda_.shared import s3_io
    panel = pd.DataFrame(
        np.random.default_rng(0).normal(0, 0.005, size=(60, 3)).cumsum(axis=0),
        index=pd.bdate_range("2022-04-01", periods=60),
        columns=["USDEUR", "USDJPY", "USD_5Y"],
    )
    s3_io.upload_parquet(panel, bucket=bucket, key="lb.parquet")


def test_run_chronos2_uploads_pathset_using_mocked_client(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("CHRONOS2_ENDPOINT", "chronos2-demo-endpoint")
    _seed_panel(s3)

    # simulate_chronos2 returns a fully-formed PathSet; patch the single seam.
    fake_ps = PathSet(
        paths=np.zeros((50, 21, 3), dtype=float),
        weights=np.full(50, 1.0 / 50),
        series=["USDEUR", "USDJPY", "USD_5Y"],
        dates=pd.bdate_range("2022-06-24", periods=21),
        source="chronos2",
    )
    with patch("tools.lambda_.run_chronos2.handler.chronos2_client.simulate_chronos2",
               return_value=fake_ps) as m:
        out = handler.handler(
            {"panel_uri": "s3://test-data/lb.parquet", "as_of": "2022-06-23",
             "horizon": 21, "n_paths": 50},
            None,
        )

    assert out["status"] == "ok"
    assert out["result"]["paths_uri"].startswith("s3://test-data/")
    m.assert_called_once()


def test_run_chronos2_rejects_invalid_horizon(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("CHRONOS2_ENDPOINT", "ep")
    out = handler.handler(
        {"panel_uri": "s3://test-data/lb.parquet", "as_of": "2022-06-23",
         "horizon": 0, "n_paths": 50},
        None,
    )
    assert out["status"] == "error"
    assert "horizon" in out["message"]
