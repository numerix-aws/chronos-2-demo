"""Transparent, rule-based regime labeler.

Produces:
- regime_features(): rolling features over the panel
- w_stress_series(): continuous [0,1] stress weight per date
- label_regimes(): discrete calm/stress label

The rules are intentionally simple so the demo can display the function.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from chronos2_demo import config

def _split_fx_rates(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split panel into (fx, rates) for the correlation feature.

    FX is exactly the configured FX_PAIRS present in the panel; rates is the
    tenor-suffixed columns. Equity/credit (and anything else) are excluded —
    they feed rolling_vol via the full panel but not rates_fx_corr.
    """
    rates = panel.filter(regex="_(2Y|5Y|10Y)$")
    fx = panel[[c for c in panel.columns if c in config.FX_PAIRS]]
    return fx, rates


def regime_features(panel: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Three rolling features keyed by date."""
    rets = panel.pct_change().dropna(how="all")
    rolling_vol = rets.rolling(window).std().mean(axis=1)
    fx, rates = _split_fx_rates(panel)
    fx_ret = fx.pct_change().mean(axis=1)
    rates_ret = rates.pct_change().mean(axis=1)
    rates_fx_corr = fx_ret.rolling(window).corr(rates_ret).abs()
    vol_of_vol = rolling_vol.rolling(window).std()
    out = pd.DataFrame({
        "rolling_vol": rolling_vol,
        "rates_fx_corr": rates_fx_corr,
        "vol_of_vol": vol_of_vol,
    })
    # Align to the panel index; warm-up rows and degenerate (zero-variance →
    # NaN/inf) features read as zero so calm periods rank as LOW stress.
    out = out.reindex(panel.index).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return out


def w_stress_series(panel: pd.DataFrame, window: int = 20) -> pd.Series:
    """Map regime features to w_stress in [0, 1] by historical-percentile rule."""
    feats = regime_features(panel, window=window)
    # Each feature: rank within its own history → [0,1]; combine by mean.
    ranks = feats.rank(pct=True)
    w = ranks.mean(axis=1).clip(0.0, 1.0)
    w.name = "w_stress"
    return w


def label_regimes(panel: pd.DataFrame, window: int = 20, threshold: float = 0.7) -> pd.Series:
    w = w_stress_series(panel, window=window)
    return pd.Series(np.where(w >= threshold, "stress", "calm"), index=w.index, name="regime")
