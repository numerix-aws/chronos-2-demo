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


import time
from typing import Optional


class Chronos2Client:
    """Thin wrapper around a SageMaker real-time endpoint."""

    def __init__(
        self,
        endpoint_name: str,
        runtime: Any,
        max_retries: int = 2,
        retry_sleep: float = 1.0,
    ) -> None:
        self.endpoint_name = endpoint_name
        self.runtime = runtime
        self.max_retries = max_retries
        self.retry_sleep = retry_sleep

    def predict(
        self,
        context: pd.DataFrame,
        horizon: int,
        n_samples: int,
        covariates: Optional[pd.DataFrame] = None,
        conditioning: Optional[Conditioning] = None,
    ) -> np.ndarray:
        body = encode_request(context, horizon, n_samples, covariates, conditioning)
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.runtime.invoke_endpoint(
                    EndpointName=self.endpoint_name,
                    ContentType="application/json",
                    Accept="application/json",
                    Body=body,
                )
                return decode_response(resp["Body"].read().decode("utf-8"))
            except Exception as e:  # botocore ClientError, network, etc.
                last_err = e
                if attempt < self.max_retries:
                    time.sleep(self.retry_sleep)
                    continue
                raise
        # unreachable, but keeps type-checkers happy:
        raise RuntimeError("retry loop exited without return") from last_err
