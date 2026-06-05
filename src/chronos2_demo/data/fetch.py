"""Public-source data fetchers. No caching here — see scripts/snapshot_data.py."""
from __future__ import annotations
import io
import pandas as pd
import requests

FRED_CSV_URL = "https://api.stlouisfed.org/fred/series/observations"
ECB_CSV_URL = "https://data-api.ecb.europa.eu/service/data/EXR"


OBS_START = "2015-01-01"


def fetch_fred_series(series_id: str, api_key: str) -> pd.Series:
    """Fetch a FRED series as a daily Series via the keyed JSON API."""
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": OBS_START,
    }
    resp = requests.get(FRED_CSV_URL, params=params, timeout=30)
    resp.raise_for_status()
    obs = resp.json()["observations"]
    rows = [(o["date"], o["value"]) for o in obs if o["value"] != "."]
    idx = pd.to_datetime([d for d, _ in rows])
    s = pd.Series([float(v) for _, v in rows], index=idx, name=series_id)
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


_CREDIT_FRED_IDS = {"US_IG_OAS": "BAMLC0A0CM", "US_HY_OAS": "BAMLH0A0HYM2"}


def fetch_credit_oas(name: str, api_key: str) -> pd.Series:
    """Fetch an ICE BofA OAS series from FRED, renamed to the panel column."""
    return fetch_fred_series(_CREDIT_FRED_IDS[name], api_key=api_key).rename(name)


import time

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
_OBS_START_EPOCH = int(time.mktime(time.strptime(OBS_START, "%Y-%m-%d")))


def fetch_yahoo_series(symbol: str) -> pd.Series:
    """Fetch a Yahoo Finance daily close series as a tz-naive dated Series."""
    params = {"period1": _OBS_START_EPOCH, "period2": int(time.time()),
              "interval": "1d"}
    resp = requests.get(f"{YAHOO_CHART_URL}/{symbol}", params=params,
                        headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    resp.raise_for_status()
    r = resp.json()["chart"]["result"][0]
    ts = r["timestamp"]
    close = r["indicators"]["quote"][0]["close"]
    idx = pd.to_datetime(ts, unit="s").normalize()
    s = pd.Series(close, index=idx, name=symbol).dropna()
    return s
