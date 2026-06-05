"""One-shot: fetch raw series, build curated parquet panels under data/curated/.

Run: python scripts/snapshot_data.py --fred-api-key $FRED_API_KEY
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
import pandas as pd

from chronos2_demo import config
from chronos2_demo.data import fetch
from chronos2_demo.data.align import align_panel
from chronos2_demo.data.covariates import load_covariates


FRED_RATE_IDS = {
    ("USD", "2Y"): "DGS2", ("USD", "5Y"): "DGS5", ("USD", "10Y"): "DGS10",
    ("EUR", "2Y"): "IRLTLT01EZM156N", ("EUR", "5Y"): "IRLTLT01EZM156N",
    ("EUR", "10Y"): "IRLTLT01EZM156N",
    ("JPY", "2Y"): "IRLTLT01JPM156N", ("JPY", "5Y"): "IRLTLT01JPM156N",
    ("JPY", "10Y"): "IRLTLT01JPM156N",
    ("GBP", "2Y"): "INTGSBGBM193N", ("GBP", "5Y"): "INTGSBGBM193N",
    ("GBP", "10Y"): "IRLTLT01GBM156N",
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--fred-api-key", required=True)
    args = p.parse_args()

    config.DATA_CURATED.mkdir(parents=True, exist_ok=True)

    series = []
    for pair in config.FX_PAIRS:
        base, quote = pair[:3], pair[3:]
        s = fetch.fetch_ecb_fx(base, quote).rename(pair)
        series.append(s)

    for ccy in config.RATES_CCYS:
        for tenor in config.RATES_TENORS:
            fred_id = FRED_RATE_IDS[(ccy, tenor)]
            s = fetch.fetch_fred_series(fred_id, args.fred_api_key).rename(f"{ccy}_{tenor}")
            series.append(s)

    for idx in config.EQUITY_INDICES:
        sym = {"SPX": "^GSPC", "NIKKEI225": "^N225"}[idx]
        series.append(fetch.fetch_yahoo_series(sym).rename(idx))

    for name in config.CREDIT_SPREADS:
        series.append(fetch.fetch_credit_oas(name, args.fred_api_key))

    # Series arrive at mixed frequencies (daily FX/USD-rates/equities; monthly
    # OECD foreign rates). Inner-joining raw collapses the panel, so reindex each
    # onto a common business-day grid and forward-fill (monthly macro carried
    # daily) before aligning.
    lo = max(s.dropna().index.min() for s in series)
    hi = min(s.dropna().index.max() for s in series)
    grid = pd.bdate_range(lo, hi)
    series = [s.reindex(grid).ffill() for s in series]
    panel = align_panel(series)
    panel.to_parquet(config.DATA_CURATED / "panel.parquet")
    print(f"wrote panel: {panel.shape} → {config.DATA_CURATED / 'panel.parquet'}")

    cov = load_covariates(args.fred_api_key)
    cov.to_parquet(config.DATA_CURATED / "covariates.parquet")
    print(f"wrote covariates: {cov.shape}")

    from chronos2_demo.data.regimes import w_stress_series
    w = w_stress_series(panel, window=20)
    w.to_frame().to_parquet(config.DATA_CURATED / "regimes.parquet")
    print(f"wrote regimes: {w.shape} → {config.DATA_CURATED / 'regimes.parquet'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
