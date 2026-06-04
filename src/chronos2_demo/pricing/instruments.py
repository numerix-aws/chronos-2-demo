"""Closed-form cross-asset instrument valuation (equity forward, CDS protection).

Same contract as pricing/xccy.value_swap_path: given a per-path `levels`
DataFrame (absolute levels at each horizon date), return USD MtM per timestep.
These make the equity/credit factors move EE/PFE/ES. See spec §4.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class EquityForward:
    id: str
    index: str            # panel column for the equity index level
    quote_ccy: str        # ccy the index is quoted in (USD, JPY, ...)
    strike: float | None  # K; None => use S at the first level row
    notional: float       # units of the index
    direction: int        # +1 long, -1 short

    @classmethod
    def from_dict(cls, d: dict) -> "EquityForward":
        return cls(id=d["id"], index=d["index"], quote_ccy=d["quote_ccy"],
                   strike=d.get("strike"), notional=float(d["notional"]),
                   direction=int(d.get("direction", 1)))


@dataclass(frozen=True)
class CDSProtection:
    id: str
    spread_series: str    # panel column for the OAS, in PERCENT
    notional: float
    rpv01: float          # risky annuity (years)
    direction: int        # +1 protection buyer (gains as spread widens)

    @classmethod
    def from_dict(cls, d: dict) -> "CDSProtection":
        return cls(id=d["id"], spread_series=d["spread_series"],
                   notional=float(d["notional"]), rpv01=float(d["rpv01"]),
                   direction=int(d.get("direction", 1)))


def value_equity_forward_path(
    fwd: EquityForward, levels: pd.DataFrame, ccy_to_usd_series_map: dict[str, str | None]
) -> np.ndarray:
    s = levels[fwd.index].to_numpy(dtype=float)
    k = s[0] if fwd.strike is None else float(fwd.strike)
    pnl_ccy = fwd.direction * fwd.notional * (s - k)
    fx_series = ccy_to_usd_series_map.get(fwd.quote_ccy)
    if fx_series is None:
        return pnl_ccy
    return pnl_ccy * levels[fx_series].to_numpy(dtype=float)


def value_cds_protection_path(cds: CDSProtection, levels: pd.DataFrame) -> np.ndarray:
    spread = levels[cds.spread_series].to_numpy(dtype=float) / 100.0  # percent → fraction
    return cds.direction * cds.notional * (spread - spread[0]) * cds.rpv01
