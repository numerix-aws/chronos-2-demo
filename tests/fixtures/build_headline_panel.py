"""Run once to produce a deterministic synthetic panel for headline regression.

Usage: python tests/fixtures/build_headline_panel.py
"""
from pathlib import Path
import numpy as np
import pandas as pd

OUT = Path(__file__).parent / "headline_panel.parquet"


def main() -> None:
    rng = np.random.default_rng(seed=20260522)
    n_obs = 600
    cols = ["USDEUR", "USDJPY", "USDGBP",
            "USD_2Y", "USD_5Y", "USD_10Y",
            "EUR_2Y", "EUR_5Y", "EUR_10Y",
            "JPY_2Y", "JPY_5Y", "JPY_10Y",
            "GBP_2Y", "GBP_5Y", "GBP_10Y"]
    base = np.array([1.08, 0.0088, 1.35,
                     0.020, 0.025, 0.030,
                     0.000, 0.005, 0.010,
                     0.000, 0.000, 0.001,
                     0.010, 0.015, 0.020])
    raw = base + rng.normal(0, 0.001, size=(n_obs, len(cols))).cumsum(axis=0) * 0.001
    # Inject a stress window so w_stress at as_of is meaningfully > 0.
    raw[400:430] += rng.normal(0, 0.02, size=(30, len(cols)))
    df = pd.DataFrame(raw, columns=cols,
                      index=pd.bdate_range("2020-01-02", periods=n_obs))
    df.to_parquet(OUT)
    print(f"wrote {OUT}: {df.shape}")


if __name__ == "__main__":
    main()
