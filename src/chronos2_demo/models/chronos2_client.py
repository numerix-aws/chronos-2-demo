"""Client for the Chronos-2 endpoint deployed via AutoGluon Cloud.

AutoGluon endpoint protocol (amazon/chronos-2):
  Request:  a long-format DataFrame (item_id, timestamp, target, [covariates...])
            plus an optional `known_covariates` future-frame; called as
            endpoint.predict(data=frame, target="target", id_column="item_id",
            timestamp_column="timestamp", prediction_length=H,
            known_covariates=known).
  Response: a long-format DataFrame with columns item_id, timestamp, mean, and
            the quantile columns "0.1".."0.9" -- per-series QUANTILES, not paths.

The endpoint returns quantiles, not paths. `Chronos2Client.predict` (Task 12)
turns the quantile block into joint sample paths via a lookback Gaussian copula.

This file is split across Tasks 11-13. Task 11 adds the frame builder/decoder.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import numpy as np
import pandas as pd

# Fixed quantile grid (Chronos-2 default). Single source of truth for both the
# request quantile_levels and decoding the returned quantile columns.
Q_LEVELS: list[float] = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]


@dataclass(frozen=True)
class Conditioning:
    """User-supplied stress narrative passed as an `anchor` known covariate.

    `series_shifts` is a per-series additive anchor applied over the first
    `n_anchor_days` of the forecast horizon (in absolute level units).
    """
    series_shifts: dict[str, float]
    n_anchor_days: int

    def to_jsonable(self) -> dict[str, Any]:
        return {"series_shifts": dict(self.series_shifts),
                "n_anchor_days": int(self.n_anchor_days)}


def build_request_frame(
    context: pd.DataFrame,
    horizon: int,
    covariates: pd.DataFrame | None,
    conditioning: Conditioning | None,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Wide lookback panel -> AutoGluon long-format (data_frame, known_covariates).

    `data_frame` has columns item_id, timestamp, target (+ covariate columns
    broadcast across items). `known_covariates`, when conditioning is supplied,
    carries a per-series `anchor` over the future horizon dates.
    """
    if covariates is not None and not context.index.equals(covariates.index):
        raise ValueError("covariates index must align with context index")

    blocks = []
    for series in context.columns:
        block = pd.DataFrame({
            "item_id": series,
            "timestamp": context.index,
            "target": context[series].values,
        })
        if covariates is not None:
            for c in covariates.columns:
                block[c] = covariates[c].values
        blocks.append(block)
    data_frame = pd.concat(blocks, ignore_index=True)

    known = None
    if conditioning is not None:
        future_dates = pd.bdate_range(
            start=context.index[-1] + pd.tseries.offsets.BDay(1), periods=horizon
        )
        kblocks = []
        for series in context.columns:
            shift = conditioning.series_shifts.get(series, 0.0)
            anchor = np.zeros(horizon)
            anchor[: min(conditioning.n_anchor_days, horizon)] = shift
            kblocks.append(pd.DataFrame({
                "item_id": series, "timestamp": future_dates, "anchor": anchor,
            }))
        known = pd.concat(kblocks, ignore_index=True)
    return data_frame, known


def decode_response(frame: pd.DataFrame, series: list[str]) -> tuple[list[float], np.ndarray]:
    """Long-format quantile frame -> (q_levels, (n_series, horizon, n_q)).

    `series` fixes the output order (matching the request panel columns).
    """
    missing = [str(ql) for ql in Q_LEVELS if str(ql) not in frame.columns]
    if missing:
        raise KeyError(f"response missing quantile columns: {missing}")
    horizon = len(frame[frame["item_id"] == series[0]])
    Q = np.empty((len(series), horizon, len(Q_LEVELS)), dtype=float)
    for s, item in enumerate(series):
        rows = frame[frame["item_id"] == item].sort_values("timestamp")
        for j, ql in enumerate(Q_LEVELS):
            Q[s, :, j] = rows[str(ql)].to_numpy(dtype=float)
    return Q_LEVELS, Q
