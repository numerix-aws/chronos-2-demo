"""Test the entrypoint as a function: env vars in, S3 upload out."""
import io
import numpy as np
import pandas as pd
import pickle
import pytest
import sys
from pathlib import Path

# Treat the entrypoint script directory as importable.
ENTRY_DIR = Path(__file__).resolve().parents[1] / "fargate" / "baseline_mc"
sys.path.insert(0, str(ENTRY_DIR))


def _seed_panel(s3_client, bucket="test-data"):
    from tools.lambda_.shared import s3_io
    rng = np.random.default_rng(0)
    panel = pd.DataFrame(
        rng.normal(0, 0.005, size=(60, 5)).cumsum(axis=0),
        index=pd.bdate_range("2022-04-01", periods=60),
        columns=["USDEUR", "USDJPY", "USD_2Y", "USD_5Y", "USD_10Y"],
    )
    s3_io.upload_parquet(panel, bucket=bucket, key="lookback.parquet")


def test_entrypoint_uploads_pathset_to_s3(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("PANEL_URI", "s3://test-data/lookback.parquet")
    monkeypatch.setenv("AS_OF", "2022-06-23")  # last business day of the 60-day panel
    monkeypatch.setenv("HORIZON", "21")
    monkeypatch.setenv("N_PATHS", "200")
    monkeypatch.setenv("N_COMPONENTS", "3")
    monkeypatch.setenv("OUTPUT_KEY", "sessions/abc/baseline.pkl")
    monkeypatch.setenv("SEED", "42")
    _seed_panel(s3)

    import importlib
    entrypoint = importlib.import_module("entrypoint")
    importlib.reload(entrypoint)
    out_uri = entrypoint.main()

    assert out_uri == "s3://test-data/sessions/abc/baseline.pkl"
    body = s3.get_object(Bucket="test-data", Key="sessions/abc/baseline.pkl")["Body"].read()
    ps = pickle.load(io.BytesIO(body))
    assert ps.paths.shape == (200, 21, 5)
    assert ps.source == "parametric"


def test_entrypoint_validates_horizon(monkeypatch, s3):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("PANEL_URI", "s3://test-data/lookback.parquet")
    monkeypatch.setenv("AS_OF", "2022-06-23")
    monkeypatch.setenv("HORIZON", "0")
    monkeypatch.setenv("N_PATHS", "200")
    monkeypatch.setenv("N_COMPONENTS", "3")
    monkeypatch.setenv("OUTPUT_KEY", "x.pkl")
    monkeypatch.setenv("SEED", "42")
    _seed_panel(s3)

    import importlib
    entrypoint = importlib.import_module("entrypoint")
    importlib.reload(entrypoint)
    with pytest.raises(ValueError, match="HORIZON"):
        entrypoint.main()
