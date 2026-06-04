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


import time
from typing import Any, Optional, Protocol
from scipy.stats import norm

_EIG_FLOOR = 1e-6


def lookback_correlation(panel: pd.DataFrame) -> np.ndarray:
    """Pearson correlation of lookback log-returns, nearest-PD guarded.

    Degenerate lookbacks (fewer than 3 return rows) fall back to identity
    (independent series).
    """
    n_series = panel.shape[1]
    log_rets = np.log(panel.clip(lower=1e-6)).diff().dropna().values
    if log_rets.shape[0] < 3:
        return np.eye(n_series)
    R = np.corrcoef(log_rets, rowvar=False)
    R = np.nan_to_num(R, nan=0.0)
    np.fill_diagonal(R, 1.0)
    # Nearest-PD guard: clip eigenvalues at a floor, rescale to unit diagonal.
    vals, vecs = np.linalg.eigh((R + R.T) / 2.0)
    vals = np.clip(vals, _EIG_FLOOR, None)
    R = vecs @ np.diag(vals) @ vecs.T
    d = np.sqrt(np.diag(R))
    R = R / np.outer(d, d)
    np.fill_diagonal(R, 1.0)
    return R


def reconstruct_paths(
    q_levels: np.ndarray,
    quantile_values: np.ndarray,
    correlation: np.ndarray,
    n_paths: int,
    seed: int = 0,
) -> np.ndarray:
    """Sample (n_paths, horizon, n_series) joint level paths.

    q_levels: (n_q,) ascending quantile levels in (0, 1).
    quantile_values: (n_series, horizon, n_q) quantile curves from the endpoint.
    correlation: (n_series, n_series) cross-series correlation for the copula.
    """
    n_series, horizon, _ = quantile_values.shape
    rng = np.random.default_rng(seed)
    # Gaussian copula: one uniform per (path, series), shared across horizon.
    chol = np.linalg.cholesky(correlation)
    u = norm.cdf(rng.standard_normal(size=(n_paths, n_series)) @ chol.T)
    q_levels = np.asarray(q_levels, dtype=float)
    paths = np.empty((n_paths, horizon, n_series), dtype=float)
    for s in range(n_series):
        for t in range(horizon):
            paths[:, t, s] = np.interp(u[:, s], q_levels, quantile_values[s, t, :])
    return paths


class _Endpoint(Protocol):
    """Structural type for the injected AutoGluon endpoint."""
    def predict(self, data: pd.DataFrame, target: str, id_column: str,
                timestamp_column: str, prediction_length: int,
                known_covariates: Optional[pd.DataFrame] = ...) -> pd.DataFrame: ...


class Chronos2Client:
    """Wrapper around a Chronos-2 endpoint deployed via AutoGluon Cloud.

    Builds the long-format request frame, calls the injected endpoint, then
    reconstructs joint sample paths client-side (the endpoint returns
    per-series quantiles, not paths). The endpoint is injected so this module
    never imports `autogluon-cloud`.
    """

    def __init__(
        self,
        endpoint: _Endpoint,
        max_retries: int = 2,
        retry_sleep: float = 1.0,
    ) -> None:
        self.endpoint = endpoint
        self.max_retries = max_retries
        self.retry_sleep = retry_sleep

    def predict(
        self,
        context: pd.DataFrame,
        horizon: int,
        n_samples: int,
        covariates: Optional[pd.DataFrame] = None,
        conditioning: Optional[Conditioning] = None,
        seed: int = 0,
    ) -> np.ndarray:
        data, known = build_request_frame(context, horizon, covariates, conditioning)
        series = list(context.columns)
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                frame = self.endpoint.predict(
                    data=data, target="target", id_column="item_id",
                    timestamp_column="timestamp", prediction_length=horizon,
                    known_covariates=known,
                )
                q_levels, Q = decode_response(frame, series=series)
                R = lookback_correlation(context)
                return reconstruct_paths(
                    np.asarray(q_levels, dtype=float), Q, R,
                    n_paths=n_samples, seed=seed,
                )
            except Exception as e:  # endpoint/network error
                last_err = e
                if attempt < self.max_retries:
                    time.sleep(self.retry_sleep)
                    continue
                raise
        # unreachable, but keeps type-checkers happy:
        raise RuntimeError("retry loop exited without return") from last_err
