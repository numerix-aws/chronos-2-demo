"""Blend two PathSets via deterministic, displayable weight rules.

This file is split across Tasks 16-17. Task 16 adds compute_weights;
Task 17 adds blend_paths that calls it and emits a final PathSet.
"""
from __future__ import annotations
import numpy as np


def _validate(w_stress: float, body_chronos_share: float, tail_quantile: float) -> None:
    if not 0.0 <= w_stress <= 1.0:
        raise ValueError(f"w_stress must be in [0,1], got {w_stress}")
    if not 0.0 <= body_chronos_share <= 1.0:
        raise ValueError(f"body_chronos_share must be in [0,1], got {body_chronos_share}")
    if not 0.0 < tail_quantile < 0.5:
        raise ValueError(f"tail_quantile must be in (0, 0.5), got {tail_quantile}")


def compute_weights(
    pnl_parametric: np.ndarray,
    pnl_chronos2: np.ndarray,
    w_stress: float,
    body_chronos_share: float = 0.1,
    tail_quantile: float = 0.05,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (w_parametric, w_chronos2), each summing to 1.

    Rules:
      For each engine independently:
        - Mark the union (top tail_quantile, bottom tail_quantile) within that engine's PnL as "tail".
        - In the tail bucket: weight ∝ (1 - w_stress) for parametric, w_stress for chronos2.
        - In the body bucket: weight ∝ (1 - body_chronos_share) for parametric,
          body_chronos_share for chronos2.
      Then renormalize each engine's vector to sum to 1.
    """
    _validate(w_stress, body_chronos_share, tail_quantile)

    def _engine_weights(pnl: np.ndarray, tail_share: float, body_share: float) -> np.ndarray:
        lo = np.quantile(pnl, tail_quantile)
        hi = np.quantile(pnl, 1 - tail_quantile)
        tail_mask = (pnl <= lo) | (pnl >= hi)
        body_mask = ~tail_mask
        n_tail = tail_mask.sum()
        n_body = body_mask.sum()
        # If a bucket is empty, fall back to uniform within the other.
        if n_tail == 0:
            return np.ones_like(pnl) / pnl.size
        if n_body == 0:
            return np.ones_like(pnl) / pnl.size
        per_tail = tail_share / n_tail
        per_body = body_share / n_body
        w = np.where(tail_mask, per_tail, per_body)
        # Normalize defensively; tail_share + body_share need not equal 1 a priori.
        return w / w.sum()

    w_par = _engine_weights(pnl_parametric, tail_share=(1 - w_stress),
                            body_share=(1 - body_chronos_share))
    w_chr = _engine_weights(pnl_chronos2, tail_share=w_stress,
                            body_share=body_chronos_share)
    return w_par, w_chr
