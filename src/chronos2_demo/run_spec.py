from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import datetime
import hashlib
import json
import re
from types import MappingProxyType
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
PROFILE_RE = re.compile(
    r"\b(stage[ -]safe|headline demo|same stage[ -]safe setup)\b",
    re.I,
)
EXPLICIT_PROFILE_RE = re.compile(
    r"as of 2022-09-30,\s*use 1,?260 trading days of history,\s*"
    r"simulate 252 trading days ahead with 500 paths per engine,\s*"
    r"and use a 0\.5305 stress weight\.\s*compare baseline and "
    r"chronos-2-augmented exposure\.",
    re.I,
)
IMPERATIVE_ACTION_RE = re.compile(
    r"\b(?:please\s+)?(?:run|compare|forecast|simulate|expose)\b",
    re.I,
)
POLITE_ACTION_RE = re.compile(
    r"\b(?:can|could|would|will)\s+you\s+(?:please\s+)?(?:run|compare|forecast|simulate|expose)\b",
    re.I,
)
WHAT_HAPPENS_IF_RE = re.compile(r"\bwhat happens if\b", re.I)
PARAMETERIZED_ACTION_RE = re.compile(
    r"\b(?:forecast|simulate)\s+[\d,]+\s+trading years?\b|\b(?:forecast|simulate)\s+[\d,]+\s+trading days\b",
    re.I,
)
EXPOSURE_ACTION_RE = re.compile(r"\b(?:calculate|compute)\s+exposure\b", re.I)
STRESS_REQUEST_RE = re.compile(
    r"\bstress\s+(?:the|this|my|a|an|test|scenario|portfolio|book|rates?|market)\b"
    r"|\b\d+(?:\.\d+)?\s*(?:%|percent)\s+stress\b|\bstress weight\b",
    re.I,
)
INFORMATIONAL_RE = re.compile(
    r"\b(?:use cases?|capabilit(?:y|ies)|catalog)\b"
    r"|\b(?:what|which|how)\b.*\bsupport(?:s|ed)?\b"
    r"|\bcan\s+(?:this|the)\s+demo\b.*\b(?:run|compare|forecast|simulate|expose)\b",
    re.I,
)
NEGATED_TOOL_RUN_RE = re.compile(r"\b(?:do not|don't)\s+run\s+tools?\b", re.I)
NUMBER_WORDS = {"one": 1, "two": 2, "five": 5, "ten": 10}
ISO_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
ENGLISH_DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+(\d{1,2}),?\s+(20\d{2})\b",
    re.I,
)
PARTIAL_ENGLISH_DATE_RE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+(?:20\d{2}|\d{1,2}(?!,?\s+20\d{2}))\b",
    re.I,
)
PARTIAL_ISO_DATE_RE = re.compile(r"\b20\d{2}-\d{2}\b(?!-\d{2})")
LOOKBACK_PATTERNS = (
    r"\b(?:look back|lookback)\D{0,12}([\d,]+)\s+trading days\b",
    r"\b([\d,]+)\s+trading days\s+of\s+(?:trading\s+)?history\b",
    r"\b(one|two|five|ten|\d+)\s+(?:trading[ -])?years?\s+(?:of\s+(?:trading\s+)?history|lookback|behind)\b",
)
HORIZON_PATTERNS = (
    r"\b(?:forecast|project|simulate)\D{0,12}([\d,]+)\s+trading days\b",
    r"\b([\d,]+)\s+trading days\s+(?:ahead|into the future|forward)\b",
    r"\b(?:forecast|project|simulate)\D{0,12}(one|two|five|ten|\d+)\s+trading years?\b",
    r"\b(one|two|five|ten|\d+)\s+trading years?\s+(?:ahead|into the future|forward|horizon)\b",
)


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
    conditioning: Mapping[str, object] | None
    provenance: Mapping[str, str]
    spec_hash: str
    execution_id: str


def canonical_run_payload(spec: RunSpec | Mapping[str, object]) -> dict[str, object]:
    value = (
        {field.name: getattr(spec, field.name) for field in fields(spec)}
        if isinstance(spec, RunSpec)
        else dict(spec)
    )
    value.pop("execution_id", None)
    value.pop("spec_hash", None)
    return _plain(value)


def compute_spec_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        canonical_run_payload(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _number(value: str) -> int:
    token = value.lower().replace(",", "")
    return NUMBER_WORDS[token] if token in NUMBER_WORDS else int(token)


def _dates(prompt: str) -> tuple[set[str], bool]:
    values = set()
    invalid = bool(PARTIAL_ENGLISH_DATE_RE.search(prompt) or PARTIAL_ISO_DATE_RE.search(prompt))
    for match in ISO_DATE_RE.finditer(prompt):
        try:
            values.add(datetime.strptime(match.group(1), "%Y-%m-%d").date().isoformat())
        except ValueError:
            invalid = True
    for match in ENGLISH_DATE_RE.finditer(prompt):
        month = match.group(1).lower()
        if month == "sept":
            month = "sep"
        fmt = "%B %d %Y" if len(month) > 3 else "%b %d %Y"
        try:
            values.add(datetime.strptime(f"{month} {match.group(2)} {match.group(3)}", fmt).date().isoformat())
        except ValueError:
            invalid = True
    return values, invalid


def _observation_values(prompt: str, patterns: tuple[str, ...]) -> set[int]:
    values = set()
    for pattern in patterns:
        for match in re.finditer(pattern, prompt, re.I):
            count = _number(match.group(1))
            values.add(count * 252 if "year" in match.group(0).lower() else count)
    return values


def _plain(value: object) -> dict[str, object] | object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    return value


def _freeze(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({
        key: _freeze(item) if isinstance(item, Mapping) else item
        for key, item in value.items()
    })


def _has_direct_execution_action(prompt: str) -> bool:
    return bool(
        IMPERATIVE_ACTION_RE.search(prompt)
        or POLITE_ACTION_RE.search(prompt)
        or WHAT_HAPPENS_IF_RE.search(prompt)
        or PARAMETERIZED_ACTION_RE.search(prompt)
        or EXPOSURE_ACTION_RE.search(prompt)
    )


def _is_stress_request(prompt: str) -> bool:
    return bool(STRESS_REQUEST_RE.search(prompt))


def _is_informational(prompt: str) -> bool:
    return bool(INFORMATIONAL_RE.search(prompt))


def _has_quantitative_run_details(prompt: str) -> bool:
    dates, invalid_date = _dates(prompt)
    return bool(
        PROFILE_RE.search(prompt)
        or dates
        or invalid_date
        or any(_observation_values(prompt, patterns) for patterns in (
            LOOKBACK_PATTERNS,
            HORIZON_PATTERNS,
        ))
        or re.search(r"\b[\d,]+\s+(?:paths|scenarios|simulations)\b", prompt, re.I)
        or re.search(
            r"\b\d+(?:\.\d+)?\s*(?:%|percent)\s+stress\b|\bstress weight\b",
            prompt,
            re.I,
        )
        or _conditioning(prompt)
    )


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
    direct_execution = _has_direct_execution_action(prompt)
    stress_request = _is_stress_request(prompt)
    if NEGATED_TOOL_RUN_RE.search(prompt):
        return Clarification(False, (), "This request does not require quantitative tools.")
    if _is_informational(prompt) and not _has_quantitative_run_details(prompt):
        return Clarification(False, (), "This request does not require quantitative tools.")
    if not direct_execution and not stress_request:
        return Clarification(False, (), "This request does not require quantitative tools.")

    profile_selected = bool(
        PROFILE_RE.search(prompt) or EXPLICIT_PROFILE_RE.fullmatch(prompt.strip())
    )
    values: dict[str, object] = dict(PROFILE) if profile_selected else {
        "schema_version": "1", "profile": None, "conditioning": None
    }
    dates, invalid_date = _dates(prompt)
    if invalid_date or len(dates) > 1:
        return Clarification(True, ("as_of_date",), "Please specify one valid as_of_date.")
    if dates:
        values["as_of_date"] = dates.pop()

    explicit_values = {
        "lookback_days": _observation_values(prompt, LOOKBACK_PATTERNS),
        "horizon": _observation_values(prompt, HORIZON_PATTERNS),
        "n_paths": {_number(value) for value in re.findall(
            r"\b([\d,]+)\s+(?:paths|scenarios|simulations)\b", prompt, re.I
        )},
    }
    percent_weights = [
        float(value) / 100.0
        for value in re.findall(r"\b(\d+(?:\.\d+)?)\s*(?:%|percent)\s+stress", prompt, re.I)
    ]
    decimal_weights = [
        float(value)
        for pattern in (
            r"\bstress weight\s+(?:of\s+)?(0(?:\.\d+)?|1(?:\.0+)?)\b",
            r"\b(0(?:\.\d+)?|1(?:\.0+)?)\s+stress weight\b",
        )
        for value in re.findall(pattern, prompt, re.I)
    ]
    explicit_values["w_stress"] = set(percent_weights + decimal_weights)
    for field, choices in explicit_values.items():
        if len(choices) > 1:
            return Clarification(True, (field,), f"Please specify one {field}.")
        if choices:
            values[field] = choices.pop()

    conditioning = _conditioning(prompt)
    if conditioning:
        values["conditioning"] = conditioning
        if not percent_weights and not decimal_weights:
            values["w_stress"] = 1.0

    missing = tuple(field for field in REQUIRED_FIELDS if field not in values)
    if missing:
        names = ", ".join(missing)
        return Clarification(True, missing, f"Please specify: {names}.")

    if not 0.0 <= float(values["w_stress"]) <= 1.0:
        return Clarification(True, ("w_stress",), "Stress weight must be between 0 and 1.")

    payload = {**values, "provenance": dict(provenance)}
    spec_hash = compute_spec_hash(payload)
    frozen_payload = {
        **payload,
        "conditioning": _freeze(payload["conditioning"]) if payload["conditioning"] else None,
        "provenance": _freeze(payload["provenance"]),
    }
    return RunSpec(
        **frozen_payload,
        spec_hash=spec_hash,
        execution_id=execution_id or uuid.uuid4().hex,
    )
