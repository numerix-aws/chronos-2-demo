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
    # Series the demo book values against (FX legs + USD/EUR/JPY/GBP rate tenors,
    # plus the cross-asset equity indices and credit OAS columns).
    series = ["USDEUR", "USDJPY", "USDGBP", "USD_5Y", "EUR_5Y", "JPY_5Y", "GBP_5Y",
              "SPX", "NIKKEI225", "US_IG_OAS", "US_HY_OAS"]
    # Realistic base levels: FX spot, rates in DECIMAL (not %), equity index points,
    # OAS in percent. A ~1.0 seed would imply 100% rates and zero swap exposure,
    # clamping PFE to 0 for every book and making the cross-asset check vacuous.
    base = np.array([1.08, 0.0088, 1.35, 0.025, 0.005, 0.000, 0.015,
                     4000.0, 28000.0, 1.2, 4.5])
    # Multiplicative random walk so levels move across the horizon (the equity
    # forward and CDS proxy value off s - s[0], so paths must drift to contribute).
    steps = rng.normal(0.0, 0.05, size=(n_paths, horizon, len(series)))
    paths = base.reshape(1, 1, -1) * np.exp(np.cumsum(steps, axis=1))
    ps = PathSet(
        paths=paths,
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


def test_price_book_prices_cross_asset_not_swaps_only(s3, monkeypatch):
    import numpy as np
    from chronos2_demo.pricing import book as bk, exposure
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("BOOK_PATH", str(DEFAULT_BOOK_PATH))
    uri = _seed_pathset(s3, "test-data", "ps.pkl")
    ps = handler._download_pickle(uri)
    out = handler.handler({"paths_uri": uri, "book_id": "demo"}, None)
    handler_pfe = np.array(out["result"]["pfe_975"])

    swaps, eq, cds = bk.load_cross_asset_book(str(DEFAULT_BOOK_PATH))
    full = exposure.compute_metrics(swaps, ps, equity_forwards=eq, cds_protection=cds)["pfe_975"]
    swaps_only = exposure.compute_metrics(swaps, ps)["pfe_975"]
    # The handler must match the full cross-asset book, and that must differ
    # from the swap-only computation (proves equity+credit are priced).
    np.testing.assert_allclose(handler_pfe, full, rtol=1e-9)
    assert not np.allclose(full, swaps_only)
