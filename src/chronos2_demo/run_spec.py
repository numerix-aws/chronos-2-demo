from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
import re
from typing import Mapping
import uuid


PROFILE = {
    "schema_version": "1",
    "profile": "stage_safe_headline_v1",
    "as_of_date": "2022-09-30",
    "lookback_days": 1260,
    "horizon": 252,
    "n_paths": 500,
    "baseline_components": 5,
    "baseline_seed": 0,
    "chronos_seed": 0,
    "w_stress": 0.5305,
    "regime_threshold": 0.7,
    "book_id": "cross_asset_demo_v1",
    "conditioning": None,
}
REQUIRED_FIELDS = tuple(k for k in PROFILE if k not in {"schema_version", "profile", "conditioning"})
PROFILE_RE = re.compile(r"\b(stage[ -]safe|headline demo|same stage[ -]safe setup)\b", re.I)
QUANT_RE = re.compile(r"\b(run|compare|forecast|simulate|exposure|stress|what happens)\b", re.I)
NEGATED_TOOL_RUN_RE = re.compile(r"\b(?:do not|don't)\s+run\s+tools?\b", re.I)
NUMBER_WORDS = {"one": 1, "two": 2, "five": 5, "ten": 10}


@dataclass(frozen=True)
class Clarification:
    is_quantitative: bool
    missing_fields: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class RunSpec:
    schema_version: str
    profile: str | None
    as_of_date: str
    lookback_days: int
    horizon: int
    n_paths: int
    baseline_components: int
    baseline_seed: int
    chronos_seed: int
    w_stress: float
    regime_threshold: float
    book_id: str
    conditioning: dict[str, object] | None
    provenance: dict[str, str]
    spec_hash: str
    execution_id: str


def canonical_run_payload(spec: RunSpec | Mapping[str, object]) -> dict[str, object]:
    value = asdict(spec) if isinstance(spec, RunSpec) else dict(spec)
    value.pop("execution_id", None)
    value.pop("spec_hash", None)
    return value


def compute_spec_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        canonical_run_payload(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _number(value: str) -> int:
    token = value.lower().replace(",", "")
    return NUMBER_WORDS[token] if token in NUMBER_WORDS else int(token)


def _date(prompt: str) -> str | None:
    iso = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", prompt)
    if iso:
        return datetime.strptime(iso.group(1), "%Y-%m-%d").date().isoformat()
    english = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December|"
        r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+(\d{1,2}),?\s+(20\d{2})\b",
        prompt,
        re.I,
    )
    if not english:
        return None
    month = english.group(1).lower()
    if month == "sept":
        month = "sep"
    fmt = "%B %d %Y" if len(month) > 3 else "%b %d %Y"
    value = f"{month} {english.group(2)} {english.group(3)}"
    return datetime.strptime(value, fmt).date().isoformat()


def _first(prompt: str, patterns: tuple[str, ...]) -> re.Match[str] | None:
    for pattern in patterns:
        match = re.search(pattern, prompt, re.I)
        if match:
            return match
    return None


def _conditioning(prompt: str) -> dict[str, object] | None:
    canonical = re.search(
        r"\bseries shifts?:\s*([A-Z0-9_]+\s*=\s*[+-]?\d+(?:\.\d+)?"
        r"(?:\s*,\s*[A-Z0-9_]+\s*=\s*[+-]?\d+(?:\.\d+)?)*)"
        r"\s*;\s*anchor\s+(\d+)\s+days?\b",
        prompt,
        re.I,
    )
    if canonical:
        shifts = {}
        for assignment in canonical.group(1).split(","):
            name, value = assignment.split("=", 1)
            shifts[name.strip().upper()] = float(value)
        return {"series_shifts": shifts, "n_anchor_days": int(canonical.group(2))}
    shock = re.search(
        r"\b([A-Z]{3})\s+rates?\s+(fall|falls|rise|rises|increase|decrease)\s+"
        r"(\d+(?:\.\d+)?)\s*(?:basis points|bp|bps)\b",
        prompt,
    )
    if not shock:
        return None
    period = re.search(r"\b(?:first|for)\s+(\d+)\s+(?:business|trading)\s+days?\b", prompt, re.I)
    tenor_clause = re.search(r"\bacross\s+(.+?)\s+tenors?\b", prompt, re.I)
    tenor_words = re.findall(r"\b(two|five|ten|2|5|10)\b", tenor_clause.group(1), re.I) \
        if tenor_clause else []
    if not period or not tenor_words:
        return None
    sign = -1 if shock.group(2).lower() in {"fall", "falls", "decrease"} else 1
    tenors = sorted({_number(value) for value in tenor_words})
    currency = shock.group(1).upper()
    return {
        "series_shifts": {
            f"{currency}_{tenor}Y": sign * float(shock.group(3)) / 100.0
            for tenor in tenors
        },
        "n_anchor_days": int(period.group(1)),
    }


def compile_run_spec(
    prompt: str,
    *,
    provenance: Mapping[str, str],
    execution_id: str | None = None,
) -> RunSpec | Clarification:
    if NEGATED_TOOL_RUN_RE.search(prompt) or not QUANT_RE.search(prompt):
        return Clarification(False, (), "This request does not require quantitative tools.")

    values: dict[str, object] = dict(PROFILE) if PROFILE_RE.search(prompt) else {
        "schema_version": "1", "profile": None, "conditioning": None
    }
    as_of = _date(prompt)
    if as_of:
        values["as_of_date"] = as_of

    lookback = _first(prompt, (
        r"\b(?:look back|lookback)\D{0,12}([\d,]+)\s+trading days\b",
        r"\b([\d,]+)\s+trading days\s+of\s+(?:trading\s+)?history\b",
        r"\b(one|two|five|ten|\d+)\s+(?:trading[ -])?years?\s+(?:of\s+(?:trading\s+)?history|lookback|behind)\b",
    ))
    if lookback:
        count = _number(lookback.group(1))
        values["lookback_days"] = count * 252 if "year" in lookback.group(0).lower() else count

    horizon = _first(prompt, (
        r"\b(?:forecast|project|simulate)\D{0,12}([\d,]+)\s+trading days\b",
        r"\b([\d,]+)\s+trading days\s+(?:ahead|into the future|forward)\b",
        r"\b(?:forecast|project|simulate)\D{0,12}(one|two|five|ten|\d+)\s+trading years?\b",
        r"\b(one|two|five|ten|\d+)\s+trading years?\s+(?:ahead|into the future|forward|horizon)\b",
    ))
    if horizon:
        count = _number(horizon.group(1))
        values["horizon"] = count * 252 if "year" in horizon.group(0).lower() else count

    paths = re.search(r"\b([\d,]+)\s+(?:paths|scenarios|simulations)\b", prompt, re.I)
    if paths:
        values["n_paths"] = _number(paths.group(1))

    percent_weight = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:%|percent)\s+stress", prompt, re.I)
    decimal_weight = re.search(r"\bstress weight\s+(?:of\s+)?(0(?:\.\d+)?|1(?:\.0+)?)\b", prompt, re.I)
    if percent_weight:
        values["w_stress"] = float(percent_weight.group(1)) / 100.0
    elif decimal_weight:
        values["w_stress"] = float(decimal_weight.group(1))

    conditioning = _conditioning(prompt)
    if conditioning:
        values["conditioning"] = conditioning
        if not percent_weight and not decimal_weight:
            values["w_stress"] = 1.0

    missing = tuple(field for field in REQUIRED_FIELDS if field not in values)
    if missing:
        names = ", ".join(missing)
        return Clarification(True, missing, f"Please specify: {names}.")

    if not 0.0 <= float(values["w_stress"]) <= 1.0:
        return Clarification(True, ("w_stress",), "Stress weight must be between 0 and 1.")

    payload = {**values, "provenance": dict(provenance)}
    spec_hash = compute_spec_hash(payload)
    return RunSpec(
        **payload,
        spec_hash=spec_hash,
        execution_id=execution_id or uuid.uuid4().hex,
    )
