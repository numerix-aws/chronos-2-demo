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


def _fetch_ecb_eur_base(quote_ccy: str) -> pd.Series:
    """Fetch one EUR-base ECB daily rate: units of quote_ccy per 1 EUR."""
    url = f"{ECB_CSV_URL}/D.{quote_ccy}.EUR.SP00.A?format=csvdata"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df["TIME_PERIOD"] = pd.to_datetime(df["TIME_PERIOD"])
    return df.set_index("TIME_PERIOD")["OBS_VALUE"].astype(float)


def fetch_ecb_fx(base_ccy: str, quote_ccy: str) -> pd.Series:
    """USD-per-foreign FX. ECB is EUR-base only, so USD crosses are triangulated.

    base="USD": USD{quote} = (USD per EUR) / (quote per EUR).  quote="EUR"
    is the direct USD/EUR leg.
    """
    if base_ccy == "USD":
        usd_per_eur = _fetch_ecb_eur_base("USD")
        if quote_ccy == "EUR":
            s = usd_per_eur
        else:
            quote_per_eur = _fetch_ecb_eur_base(quote_ccy)
            s = (usd_per_eur / quote_per_eur).dropna()
        s.name = f"{base_ccy}{quote_ccy}"
        return s
    # Legacy direct path (e.g. EUR/USD) — single key.
    flow_key = f"D.{base_ccy}.{quote_ccy}.SP00.A"
    url = f"{ECB_CSV_URL}/{flow_key}?format=csvdata"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df["TIME_PERIOD"] = pd.to_datetime(df["TIME_PERIOD"])
    s = df.set_index("TIME_PERIOD")["OBS_VALUE"].astype(float)
    s.name = f"{base_ccy}{quote_ccy}"
    return s


# Credit OAS proxy: ICE BofA OAS is licence-locked to 2023+ on FRED (no deep
# history, no ALFRED archive). BAA10Y (Moody's Baa minus 10Y Treasury, daily to
# 1986, in percent) is the deep free stand-in. US_IG_OAS = BAA10Y; US_HY_OAS is
# a fixed multiple (HY runs wider than IG). Sanctioned proxy (2026-06-05) — the
# columns keep their names + percent units but are NOT the original ICE series.
_CREDIT_PROXY_ID = "BAA10Y"
_HY_MULTIPLE = 1.7


def fetch_credit_oas(name: str, api_key: str) -> pd.Series:
    """Fetch the credit-OAS proxy (BAA10Y-based), renamed to the panel column."""
    base = fetch_fred_series(_CREDIT_PROXY_ID, api_key=api_key)
    if name == "US_IG_OAS":
        return base.rename(name)
    if name == "US_HY_OAS":
        return (base * _HY_MULTIPLE).rename(name)
    raise KeyError(name)


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
