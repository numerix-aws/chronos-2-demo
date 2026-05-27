"""Public-source data fetchers. No caching here — see scripts/snapshot_data.py."""
from __future__ import annotations
import io
import pandas as pd
import requests

FRED_CSV_URL = "https://api.stlouisfed.org/fred/series/observations"
ECB_CSV_URL = "https://sdw-wsrest.ecb.europa.eu/service/data/EXR"


def fetch_fred_series(series_id: str, api_key: str) -> pd.Series:
    """Fetch a FRED series as a daily Series indexed by DATE."""
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
    }
    # FRED supports CSV via a different endpoint; we use a stable CSV path:
    csv_url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    resp = requests.get(csv_url, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df.columns = [c.upper() for c in df.columns]
    df = df[df.iloc[:, 1] != "."]
    df["DATE"] = pd.to_datetime(df["DATE"])
    s = df.set_index("DATE").iloc[:, 0].astype(float)
    s.name = series_id
    return s


def fetch_ecb_fx(base_ccy: str, quote_ccy: str) -> pd.Series:
    """Fetch an ECB-published FX rate as quote-per-base."""
    flow_key = f"D.{base_ccy}.{quote_ccy}.SP00.A"
    url = f"{ECB_CSV_URL}/{flow_key}?format=csvdata"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df["TIME_PERIOD"] = pd.to_datetime(df["TIME_PERIOD"])
    s = df.set_index("TIME_PERIOD")["OBS_VALUE"].astype(float)
    s.name = f"{base_ccy}{quote_ccy}"
    return s
