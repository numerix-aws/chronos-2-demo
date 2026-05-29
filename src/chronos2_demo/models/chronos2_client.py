"""Client for the Chronos-2 SageMaker real-time endpoint.

Endpoint contract:
  Request:  {"context": [[...]], "covariates": [[...]] | null,
             "conditioning": {...} | null, "horizon": int, "n_samples": int}
  Response: {"samples": [[[...]]]}  shape (n_samples, horizon, n_series)

This file is split across Tasks 11-13. Task 11 adds encode/decode.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import json
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Conditioning:
    """User-supplied stress narrative passed as a prefix anchor.

    `series_shifts` is a per-series additive shift over the first
    `n_anchor_days` of the forecast horizon (in absolute level units).
    """
    series_shifts: dict[str, float]
    n_anchor_days: int

    def to_jsonable(self) -> dict[str, Any]:
        return {"series_shifts": dict(self.series_shifts),
                "n_anchor_days": int(self.n_anchor_days)}


def encode_request(
    context: pd.DataFrame,
    horizon: int,
    n_samples: int,
    covariates: pd.DataFrame | None,
    conditioning: Conditioning | None,
) -> str:
    if covariates is not None:
        if not context.index.equals(covariates.index):
            raise ValueError("covariates index must align with context index")
    payload = {
        "context": context.values.tolist(),
        "covariates": (covariates.values.tolist() if covariates is not None else None),
        "conditioning": (conditioning.to_jsonable() if conditioning is not None else None),
        "horizon": int(horizon),
        "n_samples": int(n_samples),
    }
    return json.dumps(payload)


def decode_response(body: str) -> np.ndarray:
    obj = json.loads(body)
    if "samples" not in obj:
        raise KeyError("response missing 'samples'")
    return np.asarray(obj["samples"], dtype=float)
