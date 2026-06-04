"""Test the run_chronos2 entrypoint as a function: env vars in, S3 upload out.

Mirrors test_baseline_mc_entrypoint.py: insert the entrypoint dir on sys.path
and import it as the top-level `entrypoint` module. We pop any cached `entrypoint`
first so this file and the baseline entrypoint test don't collide in one session.
"""
import importlib
import io
import sys
import numpy as np
import pandas as pd
import pickle
import pytest
from pathlib import Path
from unittest.mock import patch
from chronos2_demo.types import PathSet

ENTRY_DIR = Path(__file__).resolve().parents[1] / "fargate" / "run_chronos2"


def _seed_panel(s3_client, bucket="test-data", key="lb.parquet"):
    from tools.lambda_.shared import s3_io
    panel = pd.DataFrame(
        np.random.default_rng(0).normal(0, 0.005, size=(60, 3)).cumsum(axis=0),
        index=pd.bdate_range("2022-04-01", periods=60),
        columns=["USDEUR", "USDJPY", "USD_5Y"],
    )
    s3_io.upload_parquet(panel, bucket=bucket, key=key)


def _load_entrypoint():
    sys.path.insert(0, str(ENTRY_DIR))
    sys.modules.pop("entrypoint", None)
    import entrypoint
    return importlib.reload(entrypoint)


def test_entrypoint_runs_and_uploads_pathset(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("PANEL_URI", "s3://test-data/lb.parquet")
    monkeypatch.setenv("AS_OF", "2022-06-23")
    monkeypatch.setenv("HORIZON", "21")
    monkeypatch.setenv("N_PATHS", "50")
    monkeypatch.setenv("OUTPUT_KEY", "sessions/abc/chronos2.pkl")
    monkeypatch.setenv("CHRONOS2_ENDPOINT", "chronos2-demo-ep")
    _seed_panel(s3)

    fake_ps = PathSet(
        paths=np.zeros((50, 21, 3), dtype=float),
        weights=np.full(50, 1.0 / 50),
        series=["USDEUR", "USDJPY", "USD_5Y"],
        dates=pd.bdate_range("2022-06-24", periods=21),
        source="chronos2",
    )
    ep = _load_entrypoint()
    with patch.object(ep.sagemaker_endpoint, "open_endpoint", return_value=object()), \
         patch.object(ep.chronos2_client, "simulate_chronos2", return_value=fake_ps) as m:
        uri = ep.main()

    assert uri == "s3://test-data/sessions/abc/chronos2.pkl"
    m.assert_called_once()
    body = s3.get_object(Bucket="test-data", Key="sessions/abc/chronos2.pkl")["Body"].read()
    obj = pickle.load(io.BytesIO(body))
    assert obj.source == "chronos2"


def test_entrypoint_rejects_bad_horizon(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("PANEL_URI", "s3://test-data/lb.parquet")
    monkeypatch.setenv("AS_OF", "2022-06-23")
    monkeypatch.setenv("HORIZON", "0")
    monkeypatch.setenv("N_PATHS", "50")
    monkeypatch.setenv("OUTPUT_KEY", "sessions/abc/chronos2.pkl")
    monkeypatch.setenv("CHRONOS2_ENDPOINT", "ep")
    _seed_panel(s3)
    ep = _load_entrypoint()
    with pytest.raises(ValueError, match="HORIZON"):
        ep.main()
