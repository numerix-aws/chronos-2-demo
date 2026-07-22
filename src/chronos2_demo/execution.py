from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping

import pandas as pd


REQUIRED_COVARIATES = ("VIX", "MOVE", "WTI")
SOURCE_ROLES = {
    "parametric": "baseline",
    "chronos2": "chronos_only",
    "chronos2_conditional": "chronos_only",
    "blended": "augmented",
}


@dataclass(frozen=True)
class AlignedRunInputs:
    panel: pd.DataFrame
    covariates: pd.DataFrame


def canonical_json_sha256(value: Mapping[str, object]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def scenario_role(source: str) -> str:
    try:
        return SOURCE_ROLES[source]
    except KeyError as exc:
        raise ValueError(f"unsupported PathSet source: {source}") from exc


def _normalized(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    result = frame.copy()
    result.index = pd.DatetimeIndex(pd.to_datetime(result.index)).normalize()
    if result.index.has_duplicates:
        raise ValueError(f"{name} index contains duplicate dates")
    return result.sort_index()


def aligned_run_inputs(
    panel: pd.DataFrame,
    covariates: pd.DataFrame,
    *,
    as_of_date: str,
    lookback_days: int,
) -> AlignedRunInputs:
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")
    panel = _normalized(panel, "panel")
    covariates = _normalized(covariates, "covariates")
    missing_columns = [name for name in REQUIRED_COVARIATES if name not in covariates.columns]
    if missing_columns:
        raise ValueError(f"missing required covariates: {missing_columns}")

    as_of = pd.Timestamp(as_of_date).normalize()
    historical = panel.loc[panel.index <= as_of]
    if len(historical) < lookback_days:
        raise ValueError(
            f"panel has {len(historical)} observations through {as_of_date}; {lookback_days} required"
        )
    selected_panel = historical.tail(lookback_days).copy()
    if selected_panel.isna().any(axis=None):
        raise ValueError("selected panel contains missing values")
    selected_covariates = covariates.reindex(selected_panel.index)[list(REQUIRED_COVARIATES)].copy()
    if selected_covariates.isna().any(axis=None):
        missing_dates = selected_covariates.index[selected_covariates.isna().any(axis=1)]
        rendered = [value.strftime("%Y-%m-%d") for value in missing_dates]
        raise ValueError(f"covariates are not aligned for dates: {rendered}")
    if selected_panel.index.max() > as_of or selected_covariates.index.max() > as_of:
        raise ValueError("aligned inputs extend beyond as_of_date")
    return AlignedRunInputs(panel=selected_panel, covariates=selected_covariates)
