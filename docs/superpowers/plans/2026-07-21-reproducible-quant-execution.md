# Reproducible Quantitative Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make supported quantitative requests compile to one immutable, provenance-rich run specification; make the live agent and calibration path consume the same specification and core calculations; label results from artifact identity; stream structured exposure and diagnostic events; and prove exact cent-level reproducibility with three independent live executions.

**Architecture:** The AgentCore runtime deterministically compiles supported natural language into a `RunSpec`, persists it to `runs/<execution_id>/run_spec.json`, and executes a fixed quantitative DAG through the existing MCP Gateway before asking the model for interpretation. Existing quantitative tools receive `execution_id`, load and validate the manifest, and write deterministic per-execution artifacts. Shared core code owns input slicing, attribution, pricing, and held-out coverage. `PathSet.source`, never tool completion order, determines whether a result is baseline, Chronos-only, or augmented. The frontend consumes `run_spec`, `exposure_result`, and `diagnostics` SSE events directly. The deployment keeps the existing nine-tool AgentCore/Fargate/Lambda architecture.

**Tech Stack:** Python 3.11, NumPy/pandas, pytest, boto3/moto, Strands Agents, Amazon Bedrock AgentCore, Lambda, ECS Fargate, S3, TypeScript CDK, React 18, Cloudscape, Vitest, Playwright, and Finch.

**Reference spec:** `docs/superpowers/specs/2026-07-21-reproducible-quant-execution-design.md`

---

## Global Constraints

- The worktree already contains post-demo changes. Before each task, run `git status --short`, inspect overlapping diffs, and preserve all user changes. Stage only the files named by that task.
- Do not change the nine-tool count or replace the AgentCore, Fargate, Lambda Function URL, CloudFront OAC, WAF, or Amplify architecture.
- Do not use the model as a parser for quantitative values. The compiler either returns a complete canonical `RunSpec` or an explicit clarification response without launching tools.
- Do not add headline-only branches. The named stage-safe profile is ordinary versioned profile data, and every explicit supported prompt uses the same compiler and tool contracts.
- Do not change the `PathSet` dataclass shape. Store run identity in manifests and artifact sidecars; derive scenario identity from `PathSet.source`.
- Do not allow call order, completion order, model prose, fenced JSON, or image alt text to identify exposure results.
- Keep tests hermetic. Live SageMaker, AWS, and browser checks occur only in Task 11.
- Commit each task separately after its focused and regression tests pass.

## File Structure

```text
src/chronos2_demo/
├── run_spec.py                         # deterministic language-to-RunSpec compiler
├── execution.py                        # canonical input slicing, hashing, source roles
└── diagnostics/run_evaluation.py       # attribution and held-out coverage
tools/lambda/shared/
└── run_manifest.py                     # S3 manifest and artifact validation
agent/runtime/
├── agent.py                            # pre-model compilation and manifest persistence
└── events.py                           # Strands-to-structured-SSE translation
frontend/src/components/
├── RunDetails.tsx                      # canonical inputs and provenance
└── DiagnosticsPanel.tsx                # attribution and coverage
scripts/
└── verify_live_reproducibility.py      # independent live-run acceptance gate
```

Existing engine launchers/workers, `blend_paths`, `price_book`, `plot`, the relay, CDK stacks, and frontend state are modified in place because their current ownership boundaries remain correct.

## Canonical Contracts

The implementation must converge on these contracts before deployment.

```python
# src/chronos2_demo/run_spec.py
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

def compile_run_spec(
    prompt: str,
    *,
    provenance: Mapping[str, str],
    execution_id: str | None = None,
) -> RunSpec | Clarification:
    """Compile supported quantitative language without model inference."""
```

```json
{
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
  "conditioning": null,
  "provenance": {
    "market_snapshot_id": "curated-market-v1",
    "market_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "covariate_snapshot_id": "curated-covariates-v1",
    "covariate_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "chronos_endpoint": "chronos2-demo-endpoint",
    "chronos_model_version": "chronos-2",
    "baseline_image_digest": "sha256:baseline-image-v1",
    "chronos_image_digest": "sha256:chronos-image-v1",
    "agent_image_digest": "sha256:agent-image-v1",
    "book_version": "cross_asset_demo_v1",
    "blend_version": "importance_weight_v1",
    "pricing_version": "cross_asset_v1",
    "tool_bundle_version": "git:test",
    "strands_version": "1.30.0"
  },
  "spec_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "execution_id": "01K0QW4V5YH7Z8R9S0T1U2V3W4"
}
```

`spec_hash` is SHA-256 over sorted canonical JSON excluding `execution_id` and `spec_hash`. Every quantitative artifact returns or stores `execution_id` and `spec_hash`. Every PathSet artifact has a JSON sidecar containing its URI, SHA-256, source, scenario role, producer version, and run identity.

---

## Stage 1: Canonical Run Compilation

### Task 1: Add the immutable RunSpec and deterministic prompt compiler

**Files:**
- Create: `src/chronos2_demo/run_spec.py`
- Create: `tests/test_run_spec.py`
- Modify: `src/chronos2_demo/__init__.py`

**Interfaces:**
- Consumes: deployment provenance as `Mapping[str, str]` and a raw user prompt.
- Produces: `RunSpec`, `Clarification`, `compile_run_spec`, `canonical_run_payload`, and `compute_spec_hash` from `chronos2_demo.run_spec`.

- [ ] **Step 1: Record the pre-task worktree state**

Run:

```bash
git status --short
git diff -- src/chronos2_demo/__init__.py
```

Do not clean or reset the tree. Note any overlapping user edits before proceeding.

- [ ] **Step 2: Write failing normalization, hashing, and ambiguity tests**

Cover all of the following in `tests/test_run_spec.py`:

```python
import pytest

from chronos2_demo.run_spec import Clarification, compile_run_spec
from workflow import run_quantitative_workflow


PROVENANCE = {
    "market_snapshot_id": "market-v1",
    "market_sha256": "a" * 64,
    "covariate_snapshot_id": "cov-v1",
    "covariate_sha256": "b" * 64,
    "chronos_endpoint": "chronos2-demo",
    "chronos_model_version": "chronos-2",
    "baseline_image_digest": "sha256:baseline",
    "chronos_image_digest": "sha256:chronos",
    "agent_image_digest": "sha256:agent",
    "book_version": "cross_asset_demo_v1",
    "blend_version": "importance_weight_v1",
    "pricing_version": "cross_asset_v1",
    "tool_bundle_version": "git:test",
    "strands_version": "1.30.0",
}
HEADLINE_PROMPT = (
    "Run the stage-safe headline demo for September 30, 2022. Use five years "
    "of trading history, project one trading year into the future, generate 500 "
    "scenarios with each engine, and apply a 53.05% stress weight."
)
EXPECTED_SPEC_HASH = "1add95a87e0bc214d85f668b47c6fc0dfd7c5803a544dfd0cf1552903658de84"


@pytest.mark.parametrize("prompt", [
    "Run the stage-safe headline demo for September 30, 2022. Use five years "
    "of trading history, project one trading year into the future, generate 500 "
    "scenarios with each engine, and apply a 53.05% stress weight.",
    "Using the stage-safe settings as of 2022-09-30, look back 1260 trading "
    "days, forecast 252 trading days, "
    "use 500 paths per model, and blend with stress weight 0.5305.",
    "Use the stage safe setup on Sep 30 2022 with a five trading-year lookback, "
    "a one trading-year horizon, 500 simulations per engine and 53.05 percent stress.",
])
def test_equivalent_prompts_compile_to_same_spec_hash(prompt):
    spec = compile_run_spec(prompt, provenance=PROVENANCE, execution_id="run-a")
    assert not isinstance(spec, Clarification)
    assert spec.spec_hash == EXPECTED_SPEC_HASH
    assert spec.lookback_days == 1260
    assert spec.horizon == 252
    assert spec.n_paths == 500
    assert spec.w_stress == pytest.approx(0.5305)


def test_independent_executions_share_spec_hash_but_not_execution_id():
    first = compile_run_spec(HEADLINE_PROMPT, provenance=PROVENANCE, execution_id="run-a")
    second = compile_run_spec(HEADLINE_PROMPT, provenance=PROVENANCE, execution_id="run-b")
    assert first.spec_hash == second.spec_hash
    assert first.execution_id != second.execution_id


@pytest.mark.parametrize("prompt,field", [
    ("Run exposure for September 2022 with 500 paths.", "as_of_date"),
    ("Run exposure as of 2022-09-30 with a one-year horizon.", "lookback_days"),
    ("Run exposure as of 2022-09-30 with five years of history.", "horizon"),
    ("Run exposure as of 2022-09-30 with five years of history and one year ahead.", "n_paths"),
])
def test_ambiguous_quantitative_prompt_fails_closed(prompt, field):
    result = compile_run_spec(prompt, provenance=PROVENANCE)
    assert isinstance(result, Clarification)
    assert field in result.missing_fields


def test_greeting_does_not_compile_as_quantitative():
    result = compile_run_spec("Say hello and do not run tools.", provenance=PROVENANCE)
    assert isinstance(result, Clarification)
    assert result.is_quantitative is False


def test_rate_what_if_normalizes_to_existing_conditioning_contract():
    prompt = (
        "Using the same stage-safe setup, what happens if EUR rates fall 50 basis "
        "points across the two-, five-, and ten-year tenors for the first 30 business days?"
    )
    spec = compile_run_spec(prompt, provenance=PROVENANCE, execution_id="run-what-if")
    assert not isinstance(spec, Clarification)
    assert spec.conditioning == {
        "series_shifts": {"EUR_2Y": -0.5, "EUR_5Y": -0.5, "EUR_10Y": -0.5},
        "n_anchor_days": 30,
    }
    assert spec.w_stress == 1.0
```

The golden hash is computed from the canonical payload shown in this plan. Changing it requires an intentional schema/version change.

- [ ] **Step 3: Run the focused test and confirm the expected import failure**

Run:

```bash
pytest tests/test_run_spec.py -v
```

Expected: FAIL because `chronos2_demo.run_spec` does not exist.

- [ ] **Step 4: Implement the minimal deterministic compiler**

Implement with standard-library parsing only:

- Frozen dataclasses `RunSpec` and `Clarification`.
- A `stage_safe_headline_v1` profile dictionary containing the canonical values from the design.
- Date normalization for ISO dates and unambiguous English month dates.
- `trading year(s)` conversion at exactly 252 observations per year.
- `scenario`, `simulation`, and `path` aliases.
- Percent stress weights divided by 100; decimal stress weights preserved.
- Explicit basis-point rate conditioning, supported tenors, and business/trading-day conditioning periods.
- Stable JSON serialization and hashing.
- A quantitative-intent detector that distinguishes requests to run/compare/forecast/expose/stress from greetings and use-case questions.
- A required-field audit that returns `Clarification` instead of applying hidden defaults.

The compiler may apply profile defaults only when the user names the profile (`stage-safe`, `headline demo`, or a registered alias). Explicit values override the named profile only when they are unambiguous and supported.

Use this structure in `run_spec.py`; keep extraction helpers private and add one focused test whenever another phrase is declared supported:

```python
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
    if not QUANT_RE.search(prompt):
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
```

- [ ] **Step 5: Run focused and core tests**

Run:

```bash
pytest tests/test_run_spec.py -v
pytest -q
```

Expected: all pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add src/chronos2_demo/run_spec.py src/chronos2_demo/__init__.py tests/test_run_spec.py
git commit -m "feat: add deterministic quantitative run specs"
```

---

## Stage 2: Shared Data And Diagnostic Core

### Task 2: Centralize as-of slicing, covariate alignment, artifact hashing, and scenario roles

**Files:**
- Create: `src/chronos2_demo/execution.py`
- Create: `tests/test_execution.py`
- Modify: `src/chronos2_demo/data/alignment.py`

**Interfaces:**
- Consumes: `RunSpec` scalar fields and source `DataFrame` objects.
- Produces: `AlignedRunInputs`, `aligned_run_inputs`, `canonical_json_sha256`, and `scenario_role` from `chronos2_demo.execution`.

- [ ] **Step 1: Write failing tests for strict input boundaries and identity**

Test these contracts:

```python
from chronos2_demo.execution import (
    aligned_run_inputs,
    canonical_json_sha256,
    scenario_role,
)


def test_aligned_run_inputs_uses_exact_lookback_and_no_future_rows(panel, covariates):
    inputs = aligned_run_inputs(
        panel,
        covariates,
        as_of_date="2022-09-30",
        lookback_days=1260,
    )
    assert len(inputs.panel) == 1260
    assert len(inputs.covariates) == 1260
    assert inputs.panel.index.max().strftime("%Y-%m-%d") == "2022-09-30"
    assert inputs.covariates.index.equals(inputs.panel.index)


def test_aligned_run_inputs_rejects_missing_covariate_rows(panel, covariates):
    missing = covariates.drop(covariates.index[-10])
    with pytest.raises(ValueError, match="covariates are not aligned"):
        aligned_run_inputs(panel, missing, as_of_date="2022-09-30", lookback_days=1260)


@pytest.mark.parametrize("source,expected", [
    ("parametric", "baseline"),
    ("chronos2", "chronos_only"),
    ("chronos2_conditional", "chronos_only"),
    ("blended", "augmented"),
])
def test_scenario_role_is_derived_from_pathset_source(source, expected):
    assert scenario_role(source) == expected


def test_unknown_pathset_source_is_rejected():
    with pytest.raises(ValueError, match="unsupported PathSet source"):
        scenario_role("first_price_book_call")
```

Also prove that `canonical_json_sha256` is insensitive to dictionary insertion order and changes when content changes.

- [ ] **Step 2: Run the focused test and confirm failure**

```bash
pytest tests/test_execution.py -v
```

- [ ] **Step 3: Implement shared execution helpers**

`aligned_run_inputs` must:

1. Convert and sort both indices.
2. Select rows `<= as_of_date`.
3. Take exactly the last `lookback_days` panel observations.
4. Reindex covariates to those exact dates.
5. Reject insufficient history, duplicate indices, missing values, missing required `VIX`, `MOVE`, or `WTI` columns, or rows beyond the as-of boundary.

Do not fetch data in this module. It operates only on provided frames and is shared by Lambda handlers and calibration.

Add this complete core to `execution.py`:

```python
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
    selected_covariates = covariates.reindex(selected_panel.index)[list(REQUIRED_COVARIATES)].copy()
    if selected_covariates.isna().any(axis=None):
        missing_dates = selected_covariates.index[selected_covariates.isna().any(axis=1)]
        rendered = [value.strftime("%Y-%m-%d") for value in missing_dates]
        raise ValueError(f"covariates are not aligned for dates: {rendered}")
    if selected_panel.index.max() > as_of or selected_covariates.index.max() > as_of:
        raise ValueError("aligned inputs extend beyond as_of_date")
    return AlignedRunInputs(panel=selected_panel, covariates=selected_covariates)
```

- [ ] **Step 4: Run focused and alignment regression tests**

```bash
pytest tests/test_execution.py tests/data -v
```

- [ ] **Step 5: Commit Task 2**

```bash
git add src/chronos2_demo/execution.py src/chronos2_demo/data/alignment.py tests/test_execution.py
git commit -m "refactor: centralize canonical run inputs"
```

### Task 3: Add Chronos attribution and held-out coverage to the core

**Files:**
- Create: `src/chronos2_demo/diagnostics/run_evaluation.py`
- Create: `tests/diagnostics/test_run_evaluation.py`
- Modify: `src/chronos2_demo/diagnostics/__init__.py`

**Interfaces:**
- Consumes: canonical book, parametric/Chronos PathSets, held-out panel, and held-out regimes.
- Produces: `compute_attribution`, `compute_portfolio_coverage`, and `compute_factor_coverage` from `chronos2_demo.diagnostics.run_evaluation`.

- [ ] **Step 1: Write failing attribution tests**

Build small deterministic `PathSet` fixtures and assert five named distributions:

```python
def test_attribution_reports_all_five_distributions(book, parametric, chronos):
    report = compute_attribution(
        book,
        parametric,
        chronos,
        w_stress=0.5305,
        alpha=0.975,
    )
    assert list(report) == [
        "uniform_parametric",
        "uniform_chronos",
        "reweighted_parametric",
        "reweighted_chronos",
        "final_blend",
    ]
    assert report["uniform_parametric"]["scenario_role"] == "baseline"
    assert report["uniform_chronos"]["scenario_role"] == "chronos_only"
    assert report["final_blend"]["scenario_role"] == "augmented"
    assert report["uniform_parametric"]["delta_pfe_975"] == 0.0
```

Use a deliberately lower-risk Chronos fixture to prove the code reports a negative delta without changing labels or calling it an uplift.

- [ ] **Step 2: Write failing portfolio and factor coverage tests**

Test:

- Realized positive exposure exactly on PFE counts as covered.
- Breaches report count, average magnitude, and maximum magnitude.
- Baseline, Chronos-only, and augmented are evaluated separately.
- Central 95% factor bands report aggregate and per-series coverage.
- Calm/stress segmentation uses the canonical regime threshold.
- Any incomplete realized horizon returns `{\"available\": false, \"reason\": \"realized horizon has 17 of 252 required observations\"}` rather than padding or estimating observations.
- Future observations begin strictly after `as_of_date` and contain exactly `horizon` aligned dates.

- [ ] **Step 3: Run and confirm failures**

```bash
pytest tests/diagnostics/test_run_evaluation.py -v
```

- [ ] **Step 4: Implement the evaluation API**

Expose `compute_attribution(book: BookParts, parametric: PathSet, chronos: PathSet, *, w_stress: float, alpha: float = 0.975) -> dict[str, dict[str, object]]`, `compute_portfolio_coverage(book: BookParts, distributions: Mapping[str, PathSet], realized_panel: pd.DataFrame, *, alpha: float = 0.975) -> dict[str, object]`, and `compute_factor_coverage(distributions: Mapping[str, PathSet], realized_panel: pd.DataFrame, realized_regimes: pd.DataFrame, *, regime_threshold: float) -> dict[str, object]`.

Reuse `pricing.exposure.compute_metrics`, `pricing.exposure.portfolio_mtm`, the existing blender weighting rules, and weighted quantile helpers. Do not duplicate pricing formulas. Build component-reweighted PathSets with the original path arrays and normalized component weights; keep `PathSet` unchanged.

Implement `run_evaluation.py` with this calculation flow:

```python
from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from chronos2_demo.augmentation.blender import blend_paths, compute_weights
from chronos2_demo.diagnostics.coverage import band_coverage, regime_conditional_coverage
from chronos2_demo.pricing.exposure import compute_metrics, portfolio_mtm
from chronos2_demo.types import PathSet


BookParts = tuple[Sequence[object], Sequence[object], Sequence[object]]


def _mtm(book: BookParts, paths: PathSet) -> np.ndarray:
    swaps, equity_forwards, cds_protection = book
    return portfolio_mtm(
        swaps, paths, equity_forwards=equity_forwards, cds_protection=cds_protection
    )


def _metrics(book: BookParts, paths: PathSet, alpha: float) -> dict[str, object]:
    swaps, equity_forwards, cds_protection = book
    values = compute_metrics(
        swaps,
        paths,
        q=alpha,
        equity_forwards=equity_forwards,
        cds_protection=cds_protection,
    )
    terminal = {
        "date": values["dates"][-1].strftime("%Y-%m-%d"),
        "ee": float(values["ee"][-1]),
        "pfe_975": float(values["pfe_975"][-1]),
        "es_975": float(values["es_975"][-1]),
    }
    return {"profiles": values, "terminal": terminal}


def _weighted(paths: PathSet, weights: np.ndarray, source: str | None = None) -> PathSet:
    normalized = np.asarray(weights, dtype=float)
    normalized /= normalized.sum()
    return PathSet(
        paths=paths.paths,
        weights=normalized,
        series=list(paths.series),
        dates=paths.dates,
        source=source or paths.source,
    )


def compute_attribution(
    book: BookParts,
    parametric: PathSet,
    chronos: PathSet,
    *,
    w_stress: float,
    alpha: float = 0.975,
) -> dict[str, dict[str, object]]:
    uniform_parametric = _weighted(parametric, np.ones(parametric.n_paths))
    uniform_chronos = _weighted(chronos, np.ones(chronos.n_paths))
    pnl_parametric = _mtm(book, uniform_parametric)[:, -1]
    pnl_chronos = _mtm(book, uniform_chronos)[:, -1]
    weights_parametric, weights_chronos = compute_weights(
        pnl_parametric, pnl_chronos, w_stress=w_stress
    )
    reweighted_parametric = _weighted(parametric, weights_parametric)
    reweighted_chronos = _weighted(chronos, weights_chronos)
    final_blend = blend_paths(
        uniform_parametric,
        uniform_chronos,
        pnl_parametric,
        pnl_chronos,
        w_stress=w_stress,
    )
    distributions = {
        "uniform_parametric": uniform_parametric,
        "uniform_chronos": uniform_chronos,
        "reweighted_parametric": reweighted_parametric,
        "reweighted_chronos": reweighted_chronos,
        "final_blend": final_blend,
    }
    report = {
        name: {"terminal": _metrics(book, paths, alpha)["terminal"]}
        for name, paths in distributions.items()
    }
    baseline_pfe = float(report["uniform_parametric"]["terminal"]["pfe_975"])
    for name, values in report.items():
        terminal = values["terminal"]
        delta = float(terminal["pfe_975"]) - baseline_pfe
        values["scenario_role"] = {
            "uniform_parametric": "baseline",
            "uniform_chronos": "chronos_only",
            "reweighted_parametric": "baseline_component",
            "reweighted_chronos": "chronos_component",
            "final_blend": "augmented",
        }[name]
        values["delta_pfe_975"] = delta
        values["delta_pfe_975_pct"] = None if baseline_pfe == 0.0 else delta / baseline_pfe * 100.0
    return report


def _coverage_ready(distributions: Mapping[str, PathSet], realized: pd.DataFrame) -> str | None:
    if not distributions:
        return "no model distributions were supplied"
    reference = next(iter(distributions.values()))
    if len(realized) != reference.horizon:
        return f"realized horizon has {len(realized)} of {reference.horizon} required observations"
    if not realized.index.equals(reference.dates):
        return "realized dates do not match the forecast horizon"
    if list(realized.columns) != reference.series:
        return "realized series do not match the modeled panel"
    if realized.isna().any(axis=None):
        return "realized horizon contains missing market observations"
    return None


def compute_portfolio_coverage(
    book: BookParts,
    distributions: Mapping[str, PathSet],
    realized_panel: pd.DataFrame,
    *,
    alpha: float = 0.975,
) -> dict[str, object]:
    reason = _coverage_ready(distributions, realized_panel)
    if reason:
        return {"available": False, "reason": reason}
    realized_path = PathSet(
        paths=realized_panel.to_numpy(dtype=float)[None, :, :],
        weights=np.array([1.0]),
        series=list(realized_panel.columns),
        dates=realized_panel.index,
        source="parametric",
    )
    realized_exposure = np.maximum(_mtm(book, realized_path)[0], 0.0)
    results: dict[str, object] = {}
    for name, paths in distributions.items():
        pfe = np.asarray(_metrics(book, paths, alpha)["profiles"]["pfe_975"], dtype=float)
        breach = realized_exposure > pfe
        magnitude = np.where(breach, realized_exposure - pfe, 0.0)
        results[name] = {
            "coverage": float((~breach).mean()),
            "nominal": alpha,
            "distance_from_nominal": float(abs((~breach).mean() - alpha)),
            "breach_count": int(breach.sum()),
            "average_breach": float(magnitude[breach].mean()) if breach.any() else 0.0,
            "maximum_breach": float(magnitude.max()),
        }
    return {"available": True, "results": results}


def compute_factor_coverage(
    distributions: Mapping[str, PathSet],
    realized_panel: pd.DataFrame,
    realized_regimes: pd.DataFrame,
    *,
    regime_threshold: float,
) -> dict[str, object]:
    reason = _coverage_ready(distributions, realized_panel)
    if reason:
        return {"available": False, "reason": reason}
    if "w_stress" not in realized_regimes or not realized_regimes.index.equals(realized_panel.index):
        return {"available": False, "reason": "realized regimes do not match the forecast horizon"}
    results: dict[str, object] = {}
    def json_series(values: pd.Series) -> dict[str, float | None]:
        return {
            key: None if pd.isna(value) else float(value)
            for key, value in values.items()
        }
    for name, paths in distributions.items():
        per_series = band_coverage(paths, realized_panel, q_low=0.025, q_high=0.975)
        conditional = regime_conditional_coverage(
            paths,
            realized_panel,
            realized_regimes["w_stress"],
            q_low=0.025,
            q_high=0.975,
            stress_threshold=regime_threshold,
        )
        overall = float(per_series.mean())
        results[name] = {
            "coverage": overall,
            "nominal": 0.95,
            "distance_from_nominal": abs(overall - 0.95),
            "per_series": json_series(per_series),
            "calm": json_series(conditional["calm"]),
            "stress": json_series(conditional["stress"]),
        }
    return {"available": True, "results": results}
```

- [ ] **Step 5: Run diagnostics and full core tests**

```bash
pytest tests/diagnostics/test_run_evaluation.py tests/diagnostics tests/pricing tests/augmentation -v
pytest -q
```

- [ ] **Step 6: Commit Task 3**

```bash
git add src/chronos2_demo/diagnostics/run_evaluation.py src/chronos2_demo/diagnostics/__init__.py tests/diagnostics/test_run_evaluation.py
git commit -m "feat: measure Chronos contribution and held-out coverage"
```

---

## Stage 3: Manifest-Driven Tool Execution

### Task 4: Persist and validate run manifests and stage aligned data

**Files:**
- Create: `tools/lambda/shared/run_manifest.py`
- Create: `tools/tests/test_run_manifest.py`
- Modify: `tools/lambda/shared/s3_io.py`
- Modify: `tools/lambda/load_data/handler.py`
- Modify: `tools/tests/test_load_data.py`
- Modify: `agent/action_groups.json`
- Modify: `agent/tests/test_action_groups.py`

**Interfaces:**
- Consumes: `RunSpec` JSON persisted at the canonical S3 key.
- Produces: `load_run_spec`, `validate_argument`, `validate_artifact`, `put_artifact_sidecar`, and the manifest-driven `load_data` response.

- [ ] **Step 1: Write failing manifest validation tests**

The shared helper must load only `runs/<execution_id>/run_spec.json`, verify its own `execution_id` and recomputed `spec_hash`, and reject mismatched repeated arguments or artifact identity:

```python
def test_load_run_spec_rejects_tampered_manifest(s3_bucket):
    put_manifest(s3_bucket, execution_id="run-1", spec_hash="bad")
    with pytest.raises(ValueError, match="spec_hash"):
        load_run_spec("run-1")


def test_validate_argument_rejects_model_override(run_spec):
    with pytest.raises(ValueError, match="horizon disagrees"):
        validate_argument(run_spec, "horizon", 365)
```

Add byte, JSON, and SHA-256 helpers to `s3_io.py` with round-trip tests.

- [ ] **Step 2: Change `load_data` tests before implementation**

The handler input becomes:

```json
{"session_id": "session-1", "execution_id": "run-1"}
```

The manifest supplies `as_of_date` and `lookback_days`. The response body must include:

```json
{
  "execution_id": "run-1",
  "spec_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "panel_uri": "s3://chronos-data/runs/run-1/panel.parquet",
  "panel_sha256": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
  "covariates_uri": "s3://chronos-data/runs/run-1/covariates.parquet",
  "covariates_sha256": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
  "regimes_uri": "s3://chronos-data/runs/run-1/regimes.parquet",
  "regimes_sha256": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
  "n_rows": 1260,
  "as_of_date": "2022-09-30"
}
```

Assert exact date alignment and that the source snapshots themselves remain immutable.

- [ ] **Step 3: Update action-group contract tests**

Require `execution_id` on `load_data`, `run_baseline_mc`, `check_baseline_mc`, `run_chronos2`, `check_chronos2`, `blend_paths`, `price_book`, and `plot`. Do not add it to `lookup_use_case`. Remove model-authoritative quantitative scalars where a manifest now owns them; retain only artifact URIs, task ARNs, and explicit display choices needed by that tool.

Use this required-input matrix in both `action_groups.json` and `test_action_groups.py`:

| Tool | Required inputs |
|---|---|
| `load_data` | `session_id`, `execution_id` |
| `run_baseline_mc` | `execution_id`, `panel_uri` |
| `check_baseline_mc` | `execution_id`, `task_arn`, `paths_uri` |
| `run_chronos2` | `execution_id`, `panel_uri`, `covariates_uri` |
| `check_chronos2` | `execution_id`, `task_arn`, `paths_uri` |
| `blend_paths` | `execution_id`, `parametric_uri`, `chronos2_uri` |
| `price_book` | `execution_id`, `paths_uri` |
| `plot` | `execution_id`, `spec`, plus the URIs required by that plot role |
| `lookup_use_case` | existing `use_case` input only |

Output schemas must carry the identity and hash fields defined in Tasks 4-6; the Gateway must not strip them before the runtime receives the tool result.

- [ ] **Step 4: Run and confirm focused failures**

```bash
pytest tools/tests/test_run_manifest.py tools/tests/test_load_data.py agent/tests/test_action_groups.py -v
```

- [ ] **Step 5: Implement manifest I/O and aligned staging**

Use `chronos2_demo.execution.aligned_run_inputs`. Write run artifacts under deterministic keys. Compute each hash from the serialized object actually uploaded, not from an equivalent in-memory representation.

Before slicing, download the immutable source panel and covariate objects as bytes and verify them against the snapshot hashes pinned in the RunSpec. A source-object mismatch fails the run; it does not silently update provenance.

The action schema for `load_data` must be:

```json
{
  "name": "load_data",
  "inputSchema": {
    "type": "object",
    "properties": {
      "session_id": {"type": "string"},
      "execution_id": {"type": "string"}
    },
    "required": ["session_id", "execution_id"]
  }
}
```

Add byte-preserving helpers to `s3_io.py` and use them from `run_manifest.py`:

```python
def split_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"expected s3 URI, got {uri!r}")
    bucket, separator, key = uri[5:].partition("/")
    if not bucket or not separator or not key:
        raise ValueError(f"invalid s3 URI: {uri!r}")
    return bucket, key


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def download_bytes(uri: str) -> bytes:
    bucket, key = split_s3_uri(uri)
    return boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()


def upload_bytes(value: bytes, *, bucket: str, key: str, content_type: str) -> tuple[str, str]:
    boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=value, ContentType=content_type)
    return f"s3://{bucket}/{key}", sha256_bytes(value)


def download_json(uri: str) -> dict[str, object]:
    return json.loads(download_bytes(uri))


def upload_json(value: Mapping[str, object], *, bucket: str, key: str) -> tuple[str, str]:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return upload_bytes(raw, bucket=bucket, key=key, content_type="application/json")
```

`run_manifest.py` owns all identity validation:

```python
from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping

from chronos2_demo.execution import scenario_role
from chronos2_demo.run_spec import RunSpec, compute_spec_hash
from tools.lambda_.shared import s3_io


@dataclass(frozen=True)
class ArtifactMeta:
    execution_id: str
    spec_hash: str
    artifact_uri: str
    artifact_sha256: str
    artifact_kind: str
    source: str | None
    scenario_role: str | None
    producer_version: str


def run_spec_uri(execution_id: str) -> str:
    return f"s3://{os.environ['DATA_BUCKET']}/runs/{execution_id}/run_spec.json"


def load_run_spec(execution_id: str) -> RunSpec:
    payload = s3_io.download_json(run_spec_uri(execution_id))
    if payload.get("execution_id") != execution_id:
        raise ValueError("run manifest execution_id mismatch")
    expected = compute_spec_hash(payload)
    if payload.get("spec_hash") != expected:
        raise ValueError("run manifest spec_hash mismatch")
    return RunSpec(**payload)


def validate_argument(spec: RunSpec, name: str, supplied: object) -> None:
    expected = getattr(spec, name)
    if supplied != expected:
        raise ValueError(f"{name} disagrees with RunSpec: supplied={supplied!r}, expected={expected!r}")


def sidecar_uri(artifact_uri: str) -> str:
    suffix = artifact_uri.rsplit(".", 1)[0]
    return f"{suffix}.meta.json"


def put_artifact_sidecar(
    *,
    artifact_uri: str,
    artifact_sha256: str,
    artifact_kind: str,
    spec: RunSpec,
    producer_version: str,
    source: str | None = None,
) -> ArtifactMeta:
    meta = ArtifactMeta(
        execution_id=spec.execution_id,
        spec_hash=spec.spec_hash,
        artifact_uri=artifact_uri,
        artifact_sha256=artifact_sha256,
        artifact_kind=artifact_kind,
        source=source,
        scenario_role=scenario_role(source) if source is not None else None,
        producer_version=producer_version,
    )
    bucket, key = s3_io.split_s3_uri(sidecar_uri(artifact_uri))
    s3_io.upload_json(meta.__dict__, bucket=bucket, key=key)
    return meta


def validate_artifact(
    artifact_uri: str,
    *,
    spec: RunSpec,
    allowed_kinds: set[str],
    allowed_sources: set[str] | None = None,
) -> ArtifactMeta:
    payload = s3_io.download_json(sidecar_uri(artifact_uri))
    meta = ArtifactMeta(**payload)
    if meta.execution_id != spec.execution_id or meta.spec_hash != spec.spec_hash:
        raise ValueError("artifact run identity mismatch")
    if meta.artifact_uri != artifact_uri or meta.artifact_kind not in allowed_kinds:
        raise ValueError("artifact source identity mismatch")
    if allowed_sources is not None and meta.source not in allowed_sources:
        raise ValueError("artifact PathSet source mismatch")
    actual_hash = s3_io.sha256_bytes(s3_io.download_bytes(artifact_uri))
    if actual_hash != meta.artifact_sha256:
        raise ValueError("artifact content hash mismatch")
    return meta
```

In `load_data.handler`, replace event-owned numerical values with `spec = load_run_spec(event["execution_id"])`, verify the raw `panel.parquet` and `covariates.parquet` bytes against `spec.provenance`, and call `aligned_run_inputs`. Derive `w_stress` and labels from the verified panel with `data.regimes.w_stress_series` and `data.regimes.label_regimes`; do not load the independently stored `regimes.parquet`. Upload all three derived run frames under `runs/{spec.execution_id}/`. Serialize each frame once to bytes, upload those exact bytes, and create sidecars with `artifact_kind` values `market_panel`, `covariates`, and `regimes` and no PathSet source or scenario role.

- [ ] **Step 6: Run focused and tool regression tests**

```bash
pytest tools/tests/test_run_manifest.py tools/tests/test_load_data.py agent/tests/test_action_groups.py -v
pytest tools/tests -q
```

- [ ] **Step 7: Commit Task 4**

```bash
git add tools/lambda/shared/run_manifest.py tools/lambda/shared/s3_io.py tools/lambda/load_data/handler.py tools/tests/test_run_manifest.py tools/tests/test_load_data.py agent/action_groups.json agent/tests/test_action_groups.py
git commit -m "feat: make quantitative tools manifest driven"
```

### Task 5: Make both Fargate engines consume the same canonical inputs

**Files:**
- Modify: `tools/lambda/run_baseline_mc/handler.py`
- Modify: `tools/lambda/check_baseline_mc/handler.py`
- Modify: `tools/fargate/baseline_mc/entrypoint.py`
- Modify: `tools/lambda/run_chronos2/handler.py`
- Modify: `tools/lambda/check_chronos2/handler.py`
- Modify: `tools/fargate/run_chronos2/entrypoint.py`
- Modify: `tools/tests/test_run_baseline_mc.py`
- Modify: `tools/tests/test_check_baseline_mc.py`
- Modify: `tools/tests/test_baseline_mc_entrypoint.py`
- Modify: `tools/tests/test_run_chronos2.py`
- Modify: `tools/tests/test_check_chronos2.py`
- Modify: `tools/tests/test_run_chronos2_entrypoint.py`

**Interfaces:**
- Consumes: manifest-owned engine parameters and validated staged panel/covariate URIs.
- Produces: baseline and Chronos PathSet pickle artifacts plus `.meta.json` sidecars returned by the existing launch/poll tools.

- [ ] **Step 1: Write failing launcher tests**

Assert each launcher loads the manifest and emits ECS overrides from it. The baseline task must receive `HORIZON`, `N_PATHS`, `N_COMPONENTS`, `SEED`, `EXECUTION_ID`, `SPEC_HASH`, and the validated panel URI. The Chronos task must additionally receive `LOOKBACK_DAYS`, `CHRONOS_SEED`, and the validated covariates URI.

Prove a caller cannot substitute `n_paths`, `horizon`, or a panel from another execution.

- [ ] **Step 2: Write failing worker tests**

Assert:

- Baseline uses all 1,260 staged observations for calibration.
- Chronos calls `simulate_chronos2(panel, endpoint, covariates=covariates, horizon=252, n_paths=500, lookback_days=1260, seed=0)` rather than inheriting its 504-day library default.
- Both workers write deterministic keys `runs/<execution_id>/baseline.pkl` and `runs/<execution_id>/chronos2.pkl`.
- Both workers write sidecars with source, role, artifact SHA-256, execution identity, and producer image digest.
- Poll tools return the sidecar metadata only after the task succeeds and surface non-zero task exit codes as failed tool results.

- [ ] **Step 3: Run and confirm failures**

```bash
pytest tools/tests/test_run_baseline_mc.py tools/tests/test_check_baseline_mc.py tools/tests/test_baseline_mc_entrypoint.py tools/tests/test_run_chronos2.py tools/tests/test_check_chronos2.py tools/tests/test_run_chronos2_entrypoint.py -v
```

- [ ] **Step 4: Implement launcher and worker changes**

Keep the async launch/poll topology. Do not move Chronos inference into Lambda. The worker must use the staged panel and covariates from `load_data`; it must not redownload or reslice source snapshots independently.

Use one naming convention in both task families:

```text
runs/<execution_id>/baseline.pkl
runs/<execution_id>/baseline.meta.json
runs/<execution_id>/chronos2.pkl
runs/<execution_id>/chronos2.meta.json
```

Build ECS overrides from the manifest exactly once in each launcher. The baseline mapping is:

```python
spec = load_run_spec(event["execution_id"])
validate_artifact(event["panel_uri"], spec=spec, allowed_kinds={"market_panel"})
environment = {
    "EXECUTION_ID": spec.execution_id,
    "SPEC_HASH": spec.spec_hash,
    "PANEL_URI": event["panel_uri"],
    "OUTPUT_URI": f"s3://{os.environ['DATA_BUCKET']}/runs/{spec.execution_id}/baseline.pkl",
    "AS_OF": spec.as_of_date,
    "HORIZON": str(spec.horizon),
    "N_PATHS": str(spec.n_paths),
    "N_COMPONENTS": str(spec.baseline_components),
    "SEED": str(spec.baseline_seed),
    "PRODUCER_VERSION": spec.provenance["baseline_image_digest"],
}
overrides = [{"name": key, "value": value} for key, value in environment.items()]
```

The Chronos mapping is:

```python
spec = load_run_spec(event["execution_id"])
validate_artifact(event["panel_uri"], spec=spec, allowed_kinds={"market_panel"})
validate_artifact(event["covariates_uri"], spec=spec, allowed_kinds={"covariates"})
environment = {
    "EXECUTION_ID": spec.execution_id,
    "SPEC_HASH": spec.spec_hash,
    "PANEL_URI": event["panel_uri"],
    "COVARIATES_URI": event["covariates_uri"],
    "OUTPUT_URI": f"s3://{os.environ['DATA_BUCKET']}/runs/{spec.execution_id}/chronos2.pkl",
    "AS_OF": spec.as_of_date,
    "CHRONOS2_ENDPOINT": spec.provenance["chronos_endpoint"],
    "CONDITIONING_JSON": json.dumps(spec.conditioning, sort_keys=True) if spec.conditioning else "",
    "HORIZON": str(spec.horizon),
    "LOOKBACK_DAYS": str(spec.lookback_days),
    "N_PATHS": str(spec.n_paths),
    "SEED": str(spec.chronos_seed),
    "PRODUCER_VERSION": spec.provenance["chronos_image_digest"],
}
overrides = [{"name": key, "value": value} for key, value in environment.items()]
```

Each worker serializes once and hashes those bytes:

```python
raw = pickle.dumps(pathset, protocol=pickle.HIGHEST_PROTOCOL)
output_uri, output_sha256 = s3_io.upload_bytes(
    raw,
    bucket=output_bucket,
    key=output_key,
    content_type="application/octet-stream",
)
put_artifact_sidecar(
    artifact_uri=output_uri,
    artifact_sha256=output_sha256,
    artifact_kind="pathset",
    source=pathset.source,
    spec=spec,
    producer_version=os.environ["PRODUCER_VERSION"],
)
```

In the Chronos worker, the inference call is exactly:

```python
endpoint = sagemaker_endpoint.open_endpoint(os.environ["CHRONOS2_ENDPOINT"])
client = chronos2_client.Chronos2Client(endpoint=endpoint)
conditioning = None
if os.environ.get("CONDITIONING_JSON"):
    payload = json.loads(os.environ["CONDITIONING_JSON"])
    conditioning = chronos2_client.Conditioning(
        series_shifts={key: float(value) for key, value in payload["series_shifts"].items()},
        n_anchor_days=int(payload["n_anchor_days"]),
    )
pathset = chronos2_client.simulate_chronos2(
    client,
    panel=panel,
    as_of=os.environ["AS_OF"],
    covariates=covariates,
    horizon=int(os.environ["HORIZON"]),
    n_paths=int(os.environ["N_PATHS"]),
    lookback_days=int(os.environ["LOOKBACK_DAYS"]),
    conditioning=conditioning,
    seed=int(os.environ["SEED"]),
)
```

The poll handlers load the manifest, verify the ECS task belongs to the requested execution, require `lastStatus == "STOPPED"` and container `exitCode == 0`, then call `validate_artifact(output_uri, spec=spec, allowed_kinds={"pathset"}, allowed_sources={"parametric"})` for baseline or `validate_artifact(output_uri, spec=spec, allowed_kinds={"pathset"}, allowed_sources={"chronos2", "chronos2_conditional"})` for Chronos before returning the output URI and sidecar. A non-zero exit code returns `responses.error` with the container reason and task ARN.

- [ ] **Step 5: Run engine tool tests**

```bash
pytest tools/tests/test_run_baseline_mc.py tools/tests/test_check_baseline_mc.py tools/tests/test_baseline_mc_entrypoint.py tools/tests/test_run_chronos2.py tools/tests/test_check_chronos2.py tools/tests/test_run_chronos2_entrypoint.py -v
```

- [ ] **Step 6: Commit Task 5**

```bash
git add tools/lambda/run_baseline_mc tools/lambda/check_baseline_mc tools/fargate/baseline_mc tools/lambda/run_chronos2 tools/lambda/check_chronos2 tools/fargate/run_chronos2 tools/tests/test_run_baseline_mc.py tools/tests/test_check_baseline_mc.py tools/tests/test_baseline_mc_entrypoint.py tools/tests/test_run_chronos2.py tools/tests/test_check_chronos2.py tools/tests/test_run_chronos2_entrypoint.py
git commit -m "fix: align baseline and Chronos execution inputs"
```

### Task 6: Blend with the canonical book and write run diagnostics

**Files:**
- Modify: `tools/lambda/blend_paths/handler.py`
- Modify: `tools/tests/test_blend_paths.py`
- Modify: `tools/lambda/price_book/handler.py`
- Modify: `tools/tests/test_price_book.py`
- Modify: `tools/lambda/plot/handler.py`
- Modify: `tools/tests/test_plot.py`

**Interfaces:**
- Consumes: validated engine sidecars, the shared attribution/coverage functions, and source-derived `scenario_role`.
- Produces: blended PathSet/sidecar, `diagnostics.json`, role-keyed metrics JSON, and identity-bearing PNG results.

- [ ] **Step 1: Write failing blend tests**

Assert that `blend_paths`:

- Loads the two validated sidecars from the same execution.
- Requires one `parametric` source and one `chronos2` or `chronos2_conditional` source.
- Loads `load_cross_asset_book` using the manifest `book_id`; the swap-only `load_book` must not be called.
- Takes `w_stress`, horizon, regime threshold, and output key from the manifest.
- Writes `runs/<execution_id>/blended.pkl`, `blended.meta.json`, and `diagnostics.json`.
- Calls the shared attribution and both coverage functions.
- Marks coverage unavailable when the complete held-out horizon is absent.
- Rejects swapped execution IDs, hashes, sources, or producer versions.

- [ ] **Step 2: Write failing price identity tests**

Call `price_book` in reverse order and prove the result labels are unchanged:

```python
chronos_result = handler(event_for("chronos2.pkl"), None)
augmented_result = handler(event_for("blended.pkl"), None)
baseline_result = handler(event_for("baseline.pkl"), None)

assert body(baseline_result)["scenario_role"] == "baseline"
assert body(chronos_result)["scenario_role"] == "chronos_only"
assert body(augmented_result)["scenario_role"] == "augmented"
```

Each successful response must include:

```json
{
  "execution_id": "run-1",
  "spec_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "scenario_role": "baseline",
  "source": "parametric",
  "paths_uri": "s3://chronos-data/runs/run-1/baseline.pkl",
  "paths_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
  "metrics_uri": "s3://chronos-data/runs/run-1/metrics/baseline.json",
  "terminal": {
    "date": "2023-09-19",
    "ee": 0.0,
    "pfe_975": 0.0,
    "es_975": 0.0
  }
}
```

Metrics artifacts live at `runs/<execution_id>/metrics/<scenario_role>.json`. A retry of the same role may reproduce the same bytes; a different source may not overwrite it.

- [ ] **Step 3: Write failing plot identity tests**

Assert `pfe_overlay` accepts metrics URIs in either order, derives role from artifact content, renders baseline first and augmented second, and rejects:

- two baseline artifacts;
- Chronos-only in place of augmented;
- different `execution_id` or `spec_hash` values;
- mismatched content hashes.

Keep direct image artifact output so existing browser rendering continues to work.

- [ ] **Step 4: Run and confirm failures**

```bash
pytest tools/tests/test_blend_paths.py tools/tests/test_price_book.py tools/tests/test_plot.py -v
```

- [ ] **Step 5: Implement blend, pricing, and plotting identity**

Use `scenario_role(pathset.source)` from the core. Price the full cross-asset book for all three PathSets. Return raw numbers in structured tool output; model prose is optional commentary only.

Every plot result must include `execution_id`, `spec_hash`, a canonical `plot_role` (`regime_ribbon` or `pfe_overlay`), stable `image_s3_uri`, presigned HTTPS `image_uri`, and `image_sha256`. Compute the hash from the exact PNG bytes uploaded. Store images at `runs/<execution_id>/plots/<plot_role>.png` in the plots bucket and create a `plot` sidecar there. The browser always receives the HTTPS URI, never an `s3://` URI. The regime ribbon validates the staged regime artifact identity; the PFE overlay validates both metrics artifacts.

The three handlers use these source-derived cores. In `blend_paths.handler`:

```python
spec = load_run_spec(event["execution_id"])
parametric_meta = validate_artifact(
    event["parametric_uri"],
    spec=spec,
    allowed_kinds={"pathset"},
    allowed_sources={"parametric"},
)
chronos_meta = validate_artifact(
    event["chronos2_uri"],
    spec=spec,
    allowed_kinds={"pathset"},
    allowed_sources={"chronos2", "chronos2_conditional"},
)
parametric = pickle.loads(s3_io.download_bytes(parametric_meta.artifact_uri))
chronos = pickle.loads(s3_io.download_bytes(chronos_meta.artifact_uri))
book = book_mod.load_cross_asset_book(os.environ["BOOK_PATH"])
swaps, equity_forwards, cds_protection = book
pnl_parametric = exposure.portfolio_mtm(
    swaps, parametric, equity_forwards=equity_forwards, cds_protection=cds_protection
)[:, -1]
pnl_chronos = exposure.portfolio_mtm(
    swaps, chronos, equity_forwards=equity_forwards, cds_protection=cds_protection
)[:, -1]
blended = blender.blend_paths(
    parametric, chronos, pnl_parametric, pnl_chronos, w_stress=spec.w_stress
)
```

Serialize `blended` once, upload it, and add its `pathset` sidecar. Load the immutable full source panel, verify its deployment hash, take observations strictly after `spec.as_of_date`, and pass at most the next `spec.horizon` observations to coverage. Derive future `w_stress` and labels from that same verified full panel with the core regime functions. Build uniform copies of parametric and Chronos with `np.full(n_paths, 1.0 / n_paths)` and pass `{"baseline": uniform_parametric, "chronos_only": uniform_chronos, "augmented": blended}` to both coverage functions. Write `compute_attribution(book, parametric, chronos, w_stress=spec.w_stress)`, `compute_portfolio_coverage(book, distributions, future_panel)`, and `compute_factor_coverage(distributions, future_panel, future_regimes, regime_threshold=spec.regime_threshold)` to the diagnostics JSON contract above and return both URIs/hashes.

In `price_book.handler`, identity comes from the validated PathSet and sidecar:

```python
spec = load_run_spec(event["execution_id"])
meta = validate_artifact(
    event["paths_uri"],
    spec=spec,
    allowed_kinds={"pathset"},
    allowed_sources={"parametric", "chronos2", "chronos2_conditional", "blended"},
)
paths = pickle.loads(s3_io.download_bytes(meta.artifact_uri))
role = scenario_role(paths.source)
if role != meta.scenario_role:
    raise ValueError("PathSet source disagrees with artifact sidecar")
swaps, equity_forwards, cds_protection = book_mod.load_cross_asset_book(os.environ["BOOK_PATH"])
metrics = exposure.compute_metrics(
    swaps,
    paths,
    q=0.975,
    equity_forwards=equity_forwards,
    cds_protection=cds_protection,
)
payload = {
    "execution_id": spec.execution_id,
    "spec_hash": spec.spec_hash,
    "scenario_role": role,
    "source": paths.source,
    "paths_uri": meta.artifact_uri,
    "paths_sha256": meta.artifact_sha256,
    "ee": [float(value) for value in metrics["ee"]],
    "pfe_975": [float(value) for value in metrics["pfe_975"]],
    "es_975": [float(value) for value in metrics["es_975"]],
    "dates": [value.strftime("%Y-%m-%d") for value in metrics["dates"]],
    "terminal": {
        "date": metrics["dates"][-1].strftime("%Y-%m-%d"),
        "ee": float(metrics["ee"][-1]),
        "pfe_975": float(metrics["pfe_975"][-1]),
        "es_975": float(metrics["es_975"][-1]),
    },
}
metrics_uri, metrics_sha256 = s3_io.upload_json(
    payload,
    bucket=os.environ["DATA_BUCKET"],
    key=f"runs/{spec.execution_id}/metrics/{role}.json",
)
put_artifact_sidecar(
    artifact_uri=metrics_uri,
    artifact_sha256=metrics_sha256,
    artifact_kind="metrics",
    source=paths.source,
    spec=spec,
    producer_version=spec.provenance["pricing_version"],
)
payload.update({"metrics_uri": metrics_uri, "metrics_sha256": metrics_sha256})
return responses.ok(payload)
```

In `plot.handler`, load and validate metrics sidecars before reading JSON. Build `by_role = {payload["scenario_role"]: payload for payload in payloads}`, require `set(by_role) == {"baseline", "augmented"}`, and call the existing PFE overlay helper with `by_role["baseline"]` first. Upload the exact `Figure` PNG bytes to the deterministic plots-bucket key, create a sidecar, generate a one-hour presigned GET URL after upload, and return both URIs, the hash, and the canonical plot role.

The diagnostics document must include:

```json
{
  "execution_id": "run-1",
  "spec_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "provenance": {"book_version": "cross_asset_demo_v1"},
  "attribution": {
    "uniform_parametric": {"terminal": {"ee": 450586.45, "pfe_975": 4901670.11, "es_975": 5828331.63}},
    "uniform_chronos": {"terminal": {"ee": 212430.10, "pfe_975": 773011.20, "es_975": 910220.50}},
    "reweighted_parametric": {"terminal": {"ee": 523001.12, "pfe_975": 6101734.90, "es_975": 6700102.80}},
    "reweighted_chronos": {"terminal": {"ee": 240511.19, "pfe_975": 812445.71, "es_975": 948993.12}},
    "final_blend": {"terminal": {"ee": 524156.42, "pfe_975": 5346957.61, "es_975": 6294880.95}}
  },
  "portfolio_coverage": {"available": true, "nominal": 0.975},
  "factor_coverage": {"available": true, "nominal": 0.95}
}
```

- [ ] **Step 6: Run focused and tool regression tests**

```bash
pytest tools/tests/test_blend_paths.py tools/tests/test_price_book.py tools/tests/test_plot.py -v
pytest tools/tests -q
```

- [ ] **Step 7: Commit Task 6**

```bash
git add tools/lambda/blend_paths/handler.py tools/lambda/price_book/handler.py tools/lambda/plot/handler.py tools/tests/test_blend_paths.py tools/tests/test_price_book.py tools/tests/test_plot.py
git commit -m "fix: derive exposure identity from path provenance"
```

---

## Stage 4: One Live And Calibration Pipeline

### Task 7: Make calibration consume the same RunSpec and shared calculations

**Files:**
- Modify: `scripts/calibrate_headline.py`
- Create: `tests/test_calibrate_headline.py`

**Interfaces:**
- Consumes: `compile_run_spec`, `aligned_run_inputs`, the existing engine APIs, the canonical cross-asset book, and shared diagnostics.
- Produces: one calibration JSON document with the same RunSpec and result schema as live execution.

- [ ] **Step 1: Write a failing alignment test**

Mock endpoint inference and assert the calibration script:

- Compiles `stage_safe_headline_v1` through `compile_run_spec`.
- Uses `aligned_run_inputs` for both engines.
- Sends the identical 1,260-row panel and aligned covariates used by live tools.
- Uses 500 paths, horizon 252, baseline components 5, both seeds 0, and stress weight 0.5305 unless explicitly overridden through the same RunSpec compiler.
- Loads the same `cross_asset_demo_v1` book.
- Uses `compute_attribution`, `compute_portfolio_coverage`, and `compute_factor_coverage`.
- Emits baseline, Chronos-only, and augmented terminal metrics plus provenance.

Also add a source-code guard that fails if the script contains independent numeric defaults for `lookback_days`, `horizon`, `n_paths`, `w_stress`, or Chronos lookback.

- [ ] **Step 2: Run and confirm failure**

```bash
pytest tests/test_calibrate_headline.py -v
```

- [ ] **Step 3: Refactor the script**

The CLI accepts either `--profile stage_safe_headline_v1` or `--prompt <text>`. It may accept `--execution-id` for replay. It must not own a second set of numerical defaults.

Write the artifact with this top-level shape:

```json
{
  "run_spec": {"execution_id": "calibration-run-1", "spec_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"},
  "inputs": {"panel_rows": 1260, "covariate_rows": 1260},
  "terminal_metrics": {
    "baseline": {"ee": 450586.45, "pfe_975": 4901670.11, "es_975": 5828331.63},
    "chronos_only": {"ee": 212430.10, "pfe_975": 773011.20, "es_975": 910220.50},
    "augmented": {"ee": 524156.42, "pfe_975": 5346957.61, "es_975": 6294880.95}
  },
  "diagnostics": {
    "attribution": {"distribution_count": 5},
    "portfolio_coverage": {"available": true},
    "factor_coverage": {"available": true}
  }
}
```

Do not preserve the previous calibration number as a regression expectation because it came from a different lookback/path-count pipeline. Preserve it only in git history.

Move the script's computation into a testable `run_calibration` function with this exact dependency flow:

```python
def run_calibration(
    *,
    prompt: str,
    provenance: dict[str, str],
    panel: pd.DataFrame,
    covariates: pd.DataFrame,
    endpoint: object,
    execution_id: str,
) -> dict[str, object]:
    spec = compile_run_spec(
        prompt, provenance=provenance, execution_id=execution_id
    )
    if isinstance(spec, Clarification):
        raise ValueError(spec.message)
    inputs = aligned_run_inputs(
        panel,
        covariates,
        as_of_date=spec.as_of_date,
        lookback_days=spec.lookback_days,
    )
    parametric = baseline_mc.simulate_baseline(
        inputs.panel,
        as_of=spec.as_of_date,
        horizon=spec.horizon,
        n_paths=spec.n_paths,
        n_components=spec.baseline_components,
        seed=spec.baseline_seed,
    )
    conditioning = None
    if spec.conditioning:
        conditioning = chronos2_client.Conditioning(
            series_shifts={
                key: float(value)
                for key, value in spec.conditioning["series_shifts"].items()
            },
            n_anchor_days=int(spec.conditioning["n_anchor_days"]),
        )
    chronos = chronos2_client.simulate_chronos2(
        chronos2_client.Chronos2Client(endpoint=endpoint),
        panel=inputs.panel,
        as_of=spec.as_of_date,
        horizon=spec.horizon,
        n_paths=spec.n_paths,
        lookback_days=spec.lookback_days,
        covariates=inputs.covariates,
        conditioning=conditioning,
        seed=spec.chronos_seed,
    )
    book = bk.load_cross_asset_book(bk.DEFAULT_BOOK_PATH)
    swaps, equity_forwards, cds_protection = book
    parametric_pnl = exposure.portfolio_mtm(
        swaps,
        parametric,
        equity_forwards=equity_forwards,
        cds_protection=cds_protection,
    )[:, -1]
    chronos_pnl = exposure.portfolio_mtm(
        swaps,
        chronos,
        equity_forwards=equity_forwards,
        cds_protection=cds_protection,
    )[:, -1]
    augmented = blender.blend_paths(
        parametric,
        chronos,
        parametric_pnl,
        chronos_pnl,
        w_stress=spec.w_stress,
    )
    distributions = {
        "baseline": parametric,
        "chronos_only": chronos,
        "augmented": augmented,
    }
    future_panel = panel.loc[panel.index > pd.Timestamp(spec.as_of_date)].head(spec.horizon)
    full_regimes = pd.DataFrame({
        "w_stress": data_regimes.w_stress_series(panel),
        "regime": data_regimes.label_regimes(panel, threshold=spec.regime_threshold),
    })
    future_regimes = full_regimes.reindex(future_panel.index)
    terminal_metrics = {}
    for role, paths in distributions.items():
        values = exposure.compute_metrics(
            swaps,
            paths,
            q=0.975,
            equity_forwards=equity_forwards,
            cds_protection=cds_protection,
        )
        terminal_metrics[role] = {
            "date": values["dates"][-1].strftime("%Y-%m-%d"),
            "ee": float(values["ee"][-1]),
            "pfe_975": float(values["pfe_975"][-1]),
            "es_975": float(values["es_975"][-1]),
        }
    return {
        "run_spec": asdict(spec),
        "inputs": {"panel_rows": len(inputs.panel), "covariate_rows": len(inputs.covariates)},
        "terminal_metrics": terminal_metrics,
        "diagnostics": {
            "attribution": compute_attribution(
                book, parametric, chronos, w_stress=spec.w_stress
            ),
            "portfolio_coverage": compute_portfolio_coverage(
                book, distributions, future_panel
            ),
            "factor_coverage": compute_factor_coverage(
                distributions,
                future_panel,
                future_regimes,
                regime_threshold=spec.regime_threshold,
            ),
        },
    }
```

`main()` resolves provenance from explicit CLI arguments or a deployment-provenance JSON file, opens the endpoint, calls `run_calibration`, and writes sorted, indented JSON. Timestamp and git SHA may be recorded outside `run_spec`; they must not affect `spec_hash` or numerical comparison.

- [ ] **Step 4: Run hermetic calibration tests and core regressions**

```bash
pytest tests/test_calibrate_headline.py tests/test_run_spec.py tests/test_execution.py tests/diagnostics/test_run_evaluation.py -v
pytest -q
```

- [ ] **Step 5: Commit Task 7**

```bash
git add scripts/calibrate_headline.py tests/test_calibrate_headline.py
git commit -m "refactor: unify calibration and live calculations"
```

---

## Stage 5: Runtime Orchestration And Structured SSE

### Task 8: Compile, persist, and execute quantitative runs deterministically

**Files:**
- Modify: `agent/runtime/agent.py`
- Create: `agent/runtime/workflow.py`
- Modify: `agent/runtime/Dockerfile`
- Modify: `agent/runtime/requirements.txt`
- Modify: `agent/system_prompt.md`
- Create: `agent/tests/test_run_spec_runtime.py`
- Create: `agent/tests/test_quant_workflow.py`
- Modify: `agent/tests/test_runtime_streaming.py`
- Modify: `agent/tests/test_system_prompt.py`
- Modify: `infra/lib/tools-stack.ts`
- Modify: `infra/lib/agent-stack.ts`
- Modify: `infra/bin/app.ts`
- Modify: `infra/test/tools-stack.test.ts`
- Modify: `infra/test/agent-stack.test.ts`

**Interfaces:**
- Consumes: standard-library RunSpec compiler, deployment provenance, and direct Strands `MCPClient.call_tool_sync` access to the existing Gateway.
- Produces: persisted run manifest, first-class `run_spec` event, deterministic quantitative tool DAG, and a tool-free model interpretation pass.

- [ ] **Step 1: Write failing runtime tests**

Mock S3, the MCP client, and the Strands agent. Assert:

- A supported quantitative prompt is compiled and persisted before the model is invoked.
- The first quantitative stream event is `run_spec`.
- The model never selects tools for a quantitative request; it receives completed structured results with `tools=[]` only after the deterministic DAG succeeds.
- An ambiguous quantitative prompt emits a clarification and `done`; the model and tools are not invoked.
- A greeting bypasses RunSpec compilation and still streams ordinary text.
- A quantitative run executes `load_data`, regime plot, baseline launch/poll, Chronos launch/poll, blend, price baseline, price Chronos-only, price augmented, and PFE overlay in that exact order.
- A failed tool aborts the DAG and prevents model interpretation.

The runtime event shape is:

```json
{
  "type": "run_spec",
  "execution_id": "run-1",
  "spec_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "run_spec": {"as_of_date": "2022-09-30", "lookback_days": 1260, "horizon": 252, "n_paths": 500}
}
```

In `agent/tests/test_quant_workflow.py`, use a fake MCP client that records names and arguments and returns canned envelopes. Assert repeated polling until `ready`, `execution_id` on every call, all three source roles, both plot roles, immediate abort after a failed tool, and no `lookup_use_case` call during a quantitative run.

- [ ] **Step 2: Write failing CDK tests**

Assert the AgentCore runtime role can `s3:PutObject` and `s3:GetObject` only for the data-bucket `runs/*` prefix. S3 `HeadObject` calls are authorized by `s3:GetObject`; do not add a nonexistent `s3:HeadObject` IAM action. Assert runtime environment variables provide the data bucket and pinned provenance values. Export the data bucket from `ToolsStack` to `AgentStack` through a construct property; do not create a cross-stack CloudFormation export from `FrontendStack`.

- [ ] **Step 3: Run and confirm failures**

```bash
pytest agent/tests/test_run_spec_runtime.py agent/tests/test_quant_workflow.py agent/tests/test_runtime_streaming.py agent/tests/test_system_prompt.py -v
npm test -- --runInBand infra/test/tools-stack.test.ts infra/test/agent-stack.test.ts
```

Run the npm command from `infra/` if the package scripts require that working directory.

- [ ] **Step 4: Implement runtime compilation and persistence**

Copy the standard-library-only `chronos2_demo.run_spec` module into the AgentCore image. Resolve provenance from deployment environment variables. Persist with a conditional S3 put so an existing `execution_id` cannot be overwritten with different bytes.

The system prompt must state:

- supported quantitative tools are executed by the deterministic runtime workflow, not selected by the model;
- never restate or alter canonical scalars or structured result values;
- interpret baseline, Chronos-only, and augmented results supplied after the workflow;
- use structured tool results as numerical truth;
- never fabricate exposure values, diagnostics, image URIs, or tool success;
- ambiguous requests are resolved before the model is called.

Add these helpers to `agent.py` and call them before opening the Gateway:

```python
import boto3
import json

from chronos2_demo.run_spec import Clarification, compile_run_spec


PROVENANCE_ENV = {
    "market_snapshot_id": "MARKET_SNAPSHOT_ID",
    "market_sha256": "MARKET_SHA256",
    "covariate_snapshot_id": "COVARIATE_SNAPSHOT_ID",
    "covariate_sha256": "COVARIATE_SHA256",
    "chronos_endpoint": "CHRONOS2_ENDPOINT",
    "chronos_model_version": "CHRONOS_MODEL_VERSION",
    "baseline_image_digest": "BASELINE_IMAGE_DIGEST",
    "chronos_image_digest": "CHRONOS_IMAGE_DIGEST",
    "agent_image_digest": "AGENT_IMAGE_DIGEST",
    "book_version": "BOOK_VERSION",
    "blend_version": "BLEND_VERSION",
    "pricing_version": "PRICING_VERSION",
    "tool_bundle_version": "TOOL_BUNDLE_VERSION",
    "strands_version": "STRANDS_VERSION",
}


def _provenance() -> dict[str, str]:
    missing = [env_name for env_name in PROVENANCE_ENV.values() if not os.environ.get(env_name)]
    if missing:
        raise RuntimeError(f"missing deployment provenance: {missing}")
    return {name: os.environ[env_name] for name, env_name in PROVENANCE_ENV.items()}


def _persist_run_spec(spec) -> None:
    raw = json.dumps(spec.__dict__, sort_keys=True, separators=(",", ":")).encode("utf-8")
    boto3.client("s3").put_object(
        Bucket=os.environ["DATA_BUCKET"],
        Key=f"runs/{spec.execution_id}/run_spec.json",
        Body=raw,
        ContentType="application/json",
        IfNoneMatch="*",
    )
```

Add the standard-library compiler package to the image without installing the scientific core:

```dockerfile
RUN mkdir -p /app/chronos2_demo
COPY src/chronos2_demo/__init__.py /app/chronos2_demo/__init__.py
COPY src/chronos2_demo/run_spec.py /app/chronos2_demo/run_spec.py
```

The entrypoint begins as follows:

```python
@app.entrypoint
async def invoke(payload: dict):
    prompt = str(payload.get("prompt", ""))
    compiled = compile_run_spec(prompt, provenance=_provenance())
    if isinstance(compiled, Clarification) and compiled.is_quantitative:
        yield {"type": "text", "text": compiled.message}
        yield {"type": "done"}
        return
    if not isinstance(compiled, Clarification):
        _persist_run_spec(compiled)
        yield {
            "type": "run_spec",
            "execution_id": compiled.execution_id,
            "spec_hash": compiled.spec_hash,
            "run_spec": compiled.__dict__,
        }
        with _gateway() as gateway:
            try:
                workflow_events = run_quantitative_workflow(gateway, compiled)
                while True:
                    try:
                        outgoing = next(workflow_events)
                    except StopIteration as completed:
                        workflow = completed.value
                        break
                    yield outgoing
            except RuntimeError as exc:
                yield {"type": "error", "message": str(exc)}
                return
        model_prompt = (
            f"{prompt}\n\nThe deterministic quantitative workflow completed. "
            "Interpret these structured results without changing any value: "
            f"{json.dumps(workflow, sort_keys=True)}"
        )
        agent = Agent(
            model=BedrockModel(model_id=MODEL_ID),
            system_prompt=SYSTEM_PROMPT,
            tools=[],
            callback_handler=None,
        )
        translator = StrandsEventTranslator()
        async for event in agent.stream_async(model_prompt):
            for outgoing in translator.translate(event):
                yield outgoing
        return
    with _gateway() as gateway:
        tools = gateway.list_tools_sync()
        agent = Agent(
            model=BedrockModel(model_id=MODEL_ID),
            system_prompt=SYSTEM_PROMPT,
            tools=tools,
            callback_handler=None,
        )
        translator = StrandsEventTranslator()
        async for event in agent.stream_async(prompt):
            for outgoing in translator.translate(event):
                yield outgoing
```

Implement the deterministic DAG in `workflow.py`. The runner emits lifecycle and specialized structured events itself, so the browser updates while computation is active:

```python
from __future__ import annotations

import json
import time
from typing import Any, Callable, Generator
import uuid


def _canonical_name(name: str) -> str:
    return name.rsplit("___", 1)[-1]


def _available_tools(client) -> dict[str, str]:
    return {_canonical_name(tool.tool_name): tool.tool_name for tool in client.list_tools_sync()}


def _decode_call_result(raw: Any) -> dict[str, Any]:
    content = raw.get("content") if isinstance(raw, dict) else getattr(raw, "content", None)
    if not isinstance(content, list) or not content:
        raise RuntimeError("Gateway returned no tool content")
    first = content[0]
    json_value = first.get("json") if isinstance(first, dict) else getattr(first, "json", None)
    if isinstance(json_value, dict):
        return json_value
    text = first.get("text") if isinstance(first, dict) else getattr(first, "text", None)
    if not isinstance(text, str):
        raise RuntimeError("Gateway tool content was not JSON text")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise RuntimeError("Gateway tool payload was not an object")
    return payload


class WorkflowRunner:
    def __init__(self, client, *, sleep: Callable[[float], None] = time.sleep) -> None:
        self.client = client
        self.sleep = sleep
        self.names = _available_tools(client)

    def call(
        self, name: str, arguments: dict[str, Any]
    ) -> Generator[dict[str, Any], None, dict[str, Any]]:
        tool_use_id = str(uuid.uuid4())
        yield {
            "type": "tool",
            "tool_use_id": tool_use_id,
            "name": name,
            "status": "running",
            "input": arguments,
        }
        try:
            raw = self.client.call_tool_sync(
                tool_use_id=tool_use_id,
                name=self.names[name],
                arguments=arguments,
            )
            envelope = _decode_call_result(raw)
        except Exception as exc:
            yield {
                "type": "tool",
                "tool_use_id": tool_use_id,
                "name": name,
                "status": "failed",
                "result": {"status": "error", "message": str(exc)},
            }
            raise RuntimeError(f"{name} failed: {exc}") from exc
        if envelope.get("status") != "ok" or not isinstance(envelope.get("result"), dict):
            yield {
                "type": "tool",
                "tool_use_id": tool_use_id,
                "name": name,
                "status": "failed",
                "result": envelope,
            }
            raise RuntimeError(f"{name} failed: {envelope.get('message', 'invalid result')}")
        yield {
            "type": "tool",
            "tool_use_id": tool_use_id,
            "name": name,
            "status": "done",
            "result": envelope,
        }
        result = envelope["result"]
        if name == "price_book":
            yield {
                "type": "exposure_result",
                **{
                    key: result[key]
                    for key in (
                        "execution_id", "spec_hash", "scenario_role", "source",
                        "paths_uri", "paths_sha256", "metrics_uri", "metrics_sha256", "terminal",
                    )
                },
            }
        if name == "blend_paths":
            yield {
                "type": "diagnostics",
                **{
                    key: result[key]
                    for key in (
                        "execution_id", "spec_hash", "diagnostics_uri",
                        "diagnostics_sha256", "diagnostics",
                    )
                },
            }
        return result

    def poll(
        self,
        name: str,
        *,
        execution_id: str,
        task_arn: str,
        paths_uri: str,
    ) -> Generator[dict[str, Any], None, dict[str, Any]]:
        while True:
            result = yield from self.call(name, {
                "execution_id": execution_id,
                "task_arn": task_arn,
                "paths_uri": paths_uri,
            })
            if result["ready"]:
                return result
            self.sleep(2.0)


def run_quantitative_workflow(
    client, spec
) -> Generator[dict[str, Any], None, dict[str, Any]]:
    runner = WorkflowRunner(client)
    execution = {"execution_id": spec.execution_id}
    loaded = yield from runner.call(
        "load_data", {**execution, "session_id": spec.execution_id}
    )
    regime_plot = yield from runner.call("plot", {
        **execution,
        "spec": "regime_ribbon",
        "regimes_uri": loaded["regimes_uri"],
    })
    baseline_launch = yield from runner.call("run_baseline_mc", {
        **execution,
        "panel_uri": loaded["panel_uri"],
    })
    baseline = yield from runner.poll(
        "check_baseline_mc",
        execution_id=spec.execution_id,
        task_arn=baseline_launch["task_arn"],
        paths_uri=baseline_launch["paths_uri"],
    )
    chronos_launch = yield from runner.call("run_chronos2", {
        **execution,
        "panel_uri": loaded["panel_uri"],
        "covariates_uri": loaded["covariates_uri"],
    })
    chronos = yield from runner.poll(
        "check_chronos2",
        execution_id=spec.execution_id,
        task_arn=chronos_launch["task_arn"],
        paths_uri=chronos_launch["paths_uri"],
    )
    blend = yield from runner.call("blend_paths", {
        **execution,
        "parametric_uri": baseline["paths_uri"],
        "chronos2_uri": chronos["paths_uri"],
    })
    baseline_metrics = yield from runner.call("price_book", {
        **execution,
        "paths_uri": baseline["paths_uri"],
    })
    chronos_metrics = yield from runner.call("price_book", {
        **execution,
        "paths_uri": chronos["paths_uri"],
    })
    augmented_metrics = yield from runner.call("price_book", {
        **execution,
        "paths_uri": blend["blended_uri"],
    })
    pfe_plot = yield from runner.call("plot", {
        **execution,
        "spec": "pfe_overlay",
        "baseline_uri": baseline_metrics["metrics_uri"],
        "augmented_uri": augmented_metrics["metrics_uri"],
    })
    return {
        "run_spec": spec.__dict__,
        "exposure": {
            "baseline": baseline_metrics,
            "chronos_only": chronos_metrics,
            "augmented": augmented_metrics,
        },
        "diagnostics": blend["diagnostics"],
        "plots": {"regime_ribbon": regime_plot, "pfe_overlay": pfe_plot},
    }
```

Pin `strands-agents==1.30.0` in `agent/runtime/requirements.txt`, assert that exact value in `test_quant_workflow.py`, and publish `STRANDS_VERSION=1.30.0` in RunSpec provenance because direct-call result decoding is now a runtime contract.

In CDK, expose `public readonly dataBucket: s3.IBucket`, assign `this.dataBucket = props.dataBucket`, and grant only the run prefix:

```typescript
runtimeRole.addToPolicy(new iam.PolicyStatement({
  actions: ['s3:GetObject', 's3:PutObject'],
  resources: [`${props.tools.dataBucket.bucketArn}/runs/*`],
}));
```

Replace all three `:latest` image references with one immutable deployment tag supplied by the CDK app:

```typescript
const imageTag = app.node.tryGetContext('imageTag') ?? process.env.IMAGE_TAG;
if (!imageTag || imageTag === 'latest') {
  throw new Error('Pass an immutable image tag with -c imageTag=<git-sha>');
}
```

Add required `baselineImageTag` and `chronosImageTag` properties to `ToolsStackProps`, use them in `ecs.ContainerImage.fromEcrRepository`, and add required `agentImageTag` plus the provenance map to `AgentStackProps`. Populate every `PROVENANCE_ENV` value plus `DATA_BUCKET` in `CfnRuntime.environmentVariables`. CDK tests must assert no task/runtime uses `latest`, the selected tag appears in all three image URIs, and every required provenance variable is present.

- [ ] **Step 5: Run agent and CDK tests**

```bash
pytest agent/tests -q
```

```bash
cd infra
npm test -- --runInBand test/tools-stack.test.ts test/agent-stack.test.ts
npm run build
```

- [ ] **Step 6: Commit Task 8**

```bash
git add agent/runtime/agent.py agent/runtime/workflow.py agent/runtime/Dockerfile agent/runtime/requirements.txt agent/system_prompt.md agent/tests/test_run_spec_runtime.py agent/tests/test_quant_workflow.py agent/tests/test_runtime_streaming.py agent/tests/test_system_prompt.py infra/bin/app.ts infra/lib/tools-stack.ts infra/lib/agent-stack.ts infra/test/tools-stack.test.ts infra/test/agent-stack.test.ts
git commit -m "feat: compile immutable runs before agent orchestration"
```

### Task 9: Emit structured exposure and diagnostics events through the relay

**Files:**
- Modify: `agent/runtime/events.py`
- Modify: `agent/tests/test_runtime_streaming.py`
- Modify: `tools/lambda/sse_relay/protocol.mjs`
- Modify: `tools/lambda/sse_relay/protocol.test.mjs`
- Modify: `tools/lambda/sse_relay/index.mjs`

**Interfaces:**
- Consumes: Strands events and successful identity-bearing tool payloads.
- Produces: native `run_spec`, `exposure_result`, and `diagnostics` SSE frames alongside existing text and lifecycle frames.

- [ ] **Step 1: Write failing event translation tests**

Given successful tool results, assert the runtime emits:

```json
{"type":"exposure_result","execution_id":"run-1","spec_hash":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","scenario_role":"baseline","terminal":{"date":"2023-09-19","ee":450586.45,"pfe_975":4901670.11,"es_975":5828331.63}}
```

for each successful `price_book`, and:

```json
{"type":"diagnostics","execution_id":"run-1","spec_hash":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","diagnostics_uri":"s3://chronos-data/runs/run-1/diagnostics.json","diagnostics":{"attribution":{"distribution_count":5},"portfolio_coverage":{"available":true},"factor_coverage":{"available":true}}}
```

for successful `blend_paths` output.

Failed attempts emit lifecycle failure only. Duplicate Strands representations with the same `toolUseId` emit one lifecycle/result event. A later retry has a distinct attempt ID and cannot overwrite another scenario role.

- [ ] **Step 2: Write failing relay protocol tests**

Assert the relay forwards `run_spec`, `exposure_result`, and `diagnostics` as native SSE event types without JSON-stringifying them into text chunks or converting newlines to literal `\\n` sequences.

- [ ] **Step 3: Run and confirm failures**

```bash
pytest agent/tests/test_runtime_streaming.py -v
node --test tools/lambda/sse_relay/protocol.test.mjs
```

- [ ] **Step 4: Implement structured translation and relay forwarding**

Keep existing `text`, `tool_start`, `tool_end`, `done`, and `error` behavior. Validate successful result payloads before specialized event emission; malformed structured payloads remain visible as tool failures and never populate UI summaries.

In `events.py`, append specialized events only after the successful lifecycle completion:

```python
def _result_body(completion: dict[str, Any]) -> dict[str, Any] | None:
    if completion.get("status") != "done":
        return None
    envelope = completion.get("result")
    if not isinstance(envelope, dict) or envelope.get("status") != "ok":
        return None
    result = envelope.get("result")
    return result if isinstance(result, dict) else None


def _structured_events(completion: dict[str, Any]) -> list[dict[str, Any]]:
    result = _result_body(completion)
    if result is None:
        return []
    name = completion.get("name")
    if name == "price_book":
        required = {
            "execution_id", "spec_hash", "scenario_role", "source", "terminal",
            "paths_uri", "paths_sha256", "metrics_uri", "metrics_sha256",
        }
        if not required.issubset(result):
            return []
        return [{
            "type": "exposure_result",
            "execution_id": result["execution_id"],
            "spec_hash": result["spec_hash"],
            "scenario_role": result["scenario_role"],
            "source": result["source"],
            "paths_uri": result["paths_uri"],
            "paths_sha256": result["paths_sha256"],
            "metrics_uri": result["metrics_uri"],
            "metrics_sha256": result["metrics_sha256"],
            "terminal": result["terminal"],
        }]
    if name == "blend_paths":
        required = {"execution_id", "spec_hash", "diagnostics_uri", "diagnostics_sha256", "diagnostics"}
        if not required.issubset(result):
            return []
        return [{
            "type": "diagnostics",
            "execution_id": result["execution_id"],
            "spec_hash": result["spec_hash"],
            "diagnostics_uri": result["diagnostics_uri"],
            "diagnostics_sha256": result["diagnostics_sha256"],
            "diagnostics": result["diagnostics"],
        }]
    return []
```

At each of the two completion sites, replace `outgoing.append(completion)` with:

```python
outgoing.append(completion)
outgoing.extend(_structured_events(completion))
```

Keep relay framing byte-preserving for upstream `text/event-stream`. For non-stream fallback, `sseEvent` remains `data: <one JSON object>\n\n`; do not wrap a structured event inside `{type: "text"}`. The relay test must feed each new object through both upstream modes and compare the parsed JSON object exactly.

- [ ] **Step 5: Run runtime and relay tests**

```bash
pytest agent/tests -q
node --test tools/lambda/sse_relay/protocol.test.mjs
```

- [ ] **Step 6: Commit Task 9**

```bash
git add agent/runtime/events.py agent/tests/test_runtime_streaming.py tools/lambda/sse_relay/protocol.mjs tools/lambda/sse_relay/protocol.test.mjs tools/lambda/sse_relay/index.mjs
git commit -m "feat: stream structured quantitative results"
```

---

## Stage 6: Frontend Identity And Diagnostics

### Task 10: Render structured RunSpec, exposure, diagnostics, and image artifacts

**Files:**
- Modify: `frontend/src/api/stream.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/ExposureSummary.tsx`
- Create: `frontend/src/components/RunDetails.tsx`
- Create: `frontend/src/components/DiagnosticsPanel.tsx`
- Modify: `frontend/src/components/ImageViewer.tsx`
- Modify: `frontend/tests/api/stream.test.ts`
- Modify: `frontend/tests/App.test.tsx`
- Create: `frontend/tests/components/RunDetails.test.tsx`
- Create: `frontend/tests/components/DiagnosticsPanel.test.tsx`
- Modify: `frontend/tests/e2e/happy_path.spec.ts`

**Interfaces:**
- Consumes: typed native SSE events from Task 9.
- Produces: role-keyed exposure state, RunSpec details, diagnostics views, and direct image rendering.

- [ ] **Step 1: Write failing stream parser tests**

Add typed events:

```typescript
type RunSpecEvent = {
  type: 'run_spec';
  execution_id: string;
  spec_hash: string;
  run_spec: RunSpec;
};

type ExposureResultEvent = {
  type: 'exposure_result';
  execution_id: string;
  spec_hash: string;
  scenario_role: 'baseline' | 'chronos_only' | 'augmented';
  terminal: TerminalExposure;
};

type DiagnosticsEvent = {
  type: 'diagnostics';
  execution_id: string;
  spec_hash: string;
  diagnostics_uri: string;
  diagnostics: RunDiagnostics;
};
```

Assert split network chunks and multiple events in one chunk parse correctly.

- [ ] **Step 2: Write failing identity and order tests**

Feed events in the order `augmented`, `chronos_only`, `baseline`. Assert the UI renders the correct labels and values. Remove expectations tied to `priceBookResultCount`.

Also assert:

- A second execution cannot overwrite the first execution's rows.
- Duplicate role events with identical hashes are idempotent.
- Conflicting duplicate role events show an error state.
- Failed tool attempts do not create exposure rows.
- The summary is complete without model-generated markers or fenced JSON.
- Absolute and percentage PFE deltas are computed from structured baseline and augmented rows; percent is omitted when baseline is zero.

- [ ] **Step 3: Write failing diagnostics and image tests**

Render the five attribution distributions, portfolio coverage, and factor coverage. Show an explicit unavailable reason when coverage is unavailable. Verify direct plot artifact events produce browser image URLs and that a failed image load shows a concise error without exposing raw escaped markdown.

- [ ] **Step 4: Run and confirm failures**

```bash
cd frontend
npm test -- --run
```

- [ ] **Step 5: Implement the frontend state model**

Use a key of `${execution_id}:${scenario_role}`. Keep current text streaming and tool trace panels. Treat structured events as authoritative; retain legacy model-JSON parsing only as a temporary non-authoritative compatibility fallback, clearly isolated and never allowed to overwrite structured rows.

Use compact Cloudscape tables or key-value layouts. Do not put cards inside cards. Keep raw dollar precision in state and format only at render time.

Extend `StreamEvent` and `decodeStructuredEvent` with concrete guards:

```typescript
export type ScenarioRole = 'baseline' | 'chronos_only' | 'augmented';

export type TerminalExposure = {
  date: string;
  ee: number;
  pfe_975: number;
  es_975: number;
};

export type RunSpecEvent = {
  type: 'run_spec';
  executionId: string;
  specHash: string;
  runSpec: Record<string, unknown>;
};

export type ExposureResultEvent = {
  type: 'exposure_result';
  executionId: string;
  specHash: string;
  scenarioRole: ScenarioRole;
  source: string;
  metricsUri: string;
  metricsSha256: string;
  terminal: TerminalExposure;
};

export type DiagnosticsEvent = {
  type: 'diagnostics';
  executionId: string;
  specHash: string;
  diagnosticsUri: string;
  diagnosticsSha256: string;
  diagnostics: Record<string, unknown>;
};
```

```typescript
if (
  event.type === 'run_spec' &&
  typeof event.execution_id === 'string' &&
  typeof event.spec_hash === 'string' &&
  asRecord(event.run_spec)
) {
  return {
    type: 'run_spec',
    executionId: event.execution_id,
    specHash: event.spec_hash,
    runSpec: event.run_spec as Record<string, unknown>,
  };
}
if (
  event.type === 'exposure_result' &&
  typeof event.execution_id === 'string' &&
  typeof event.spec_hash === 'string' &&
  (event.scenario_role === 'baseline' ||
    event.scenario_role === 'chronos_only' ||
    event.scenario_role === 'augmented') &&
  typeof event.metrics_uri === 'string' &&
  typeof event.metrics_sha256 === 'string' &&
  asRecord(event.terminal)
) {
  const terminal = event.terminal as Record<string, unknown>;
  if (
    typeof terminal.date === 'string' &&
    typeof terminal.ee === 'number' &&
    typeof terminal.pfe_975 === 'number' &&
    typeof terminal.es_975 === 'number'
  ) {
    return {
      type: 'exposure_result',
      executionId: event.execution_id,
      specHash: event.spec_hash,
      scenarioRole: event.scenario_role,
      source: String(event.source),
      metricsUri: event.metrics_uri,
      metricsSha256: event.metrics_sha256,
      terminal: terminal as TerminalExposure,
    };
  }
}
if (
  event.type === 'diagnostics' &&
  typeof event.execution_id === 'string' &&
  typeof event.spec_hash === 'string' &&
  typeof event.diagnostics_uri === 'string' &&
  typeof event.diagnostics_sha256 === 'string' &&
  asRecord(event.diagnostics)
) {
  return {
    type: 'diagnostics',
    executionId: event.execution_id,
    specHash: event.spec_hash,
    diagnosticsUri: event.diagnostics_uri,
    diagnosticsSha256: event.diagnostics_sha256,
    diagnostics: event.diagnostics as Record<string, unknown>,
  };
}
```

Add identity fields to `ExposureRow` and create rows only from `ExposureResultEvent`:

```typescript
const ROLE_LABELS: Record<ScenarioRole, string> = {
  baseline: 'Baseline',
  chronos_only: 'Chronos-only',
  augmented: 'Augmented',
};

function exposureRowFromEvent(event: ExposureResultEvent): ExposureRow {
  return {
    executionId: event.executionId,
    specHash: event.specHash,
    scenarioRole: event.scenarioRole,
    metricsSha256: event.metricsSha256,
    label: ROLE_LABELS[event.scenarioRole],
    date: event.terminal.date,
    ee: event.terminal.ee,
    pfe975: event.terminal.pfe_975,
    es975: event.terminal.es_975,
  };
}
```

Replace `priceBookResultCount` with a role-keyed map in `App`:

```typescript
const [runSpec, setRunSpec] = useState<RunSpecEvent | null>(null);
const [exposureByIdentity, setExposureByIdentity] = useState<Record<string, ExposureRow>>({});
const [diagnostics, setDiagnostics] = useState<DiagnosticsEvent | null>(null);
const [identityError, setIdentityError] = useState<string | null>(null);

function acceptExposure(event: ExposureResultEvent) {
  const key = `${event.executionId}:${event.scenarioRole}`;
  const incoming = exposureRowFromEvent(event);
  setExposureByIdentity((previous) => {
    const existing = previous[key];
    if (existing && existing.metricsSha256 !== incoming.metricsSha256) {
      setIdentityError(`Conflicting ${incoming.label} result for execution ${event.executionId}.`);
      return previous;
    }
    return existing ? previous : { ...previous, [key]: incoming };
  });
}
```

Inside the stream loop, handle `run_spec`, `exposure_result`, and `diagnostics` before the generic error branch. Reset the four states at the start of a request. Derive `exposureRows` by filtering the current `runSpec.executionId` and sorting with `baseline: 0`, `chronos_only: 1`, `augmented: 2`. `RunDetails` renders the canonical inputs plus shortened hashes. `DiagnosticsPanel` renders the five attribution rows and coverage tables from the structured document. `ExposureSummary` computes PFE delta from the baseline and augmented rows in memory and never parses assistant text when structured rows exist.

Replace the What-if form's parameter-name prompt with compiler-supported language:

```typescript
let prompt =
  `Re-run the stage-safe setup as of ${p.as_of_date}. Look back ${p.lookback_days} ` +
  `trading days, project ${p.horizon} trading days into the future, generate ` +
  `${p.n_paths} scenarios with each engine, and apply a stress weight of ${p.w_stress}. `;
if (p.conditioning) {
  const shifts = Object.entries(p.conditioning.series_shifts)
    .map(([name, value]) => `${name}=${value}`)
    .join(', ');
  prompt += `Use series shifts: ${shifts}; anchor ${p.conditioning.n_anchor_days} days. `;
}
prompt += 'Compare baseline, Chronos-only, and augmented EE, PFE 97.5%, and ES 97.5%.';
```

Add a compiler test for the emitted `series shifts: EUR_2Y=-0.5; anchor 30 days` clause and a frontend test that compiles the form's exact output to the expected profile values.

Update direct plot extraction to use the canonical role and HTTPS URL:

```typescript
function plotArtifactFromToolResult(value: unknown): PlotArtifact | null {
  const envelope = asRecord(value);
  const result = asRecord(envelope?.result) ?? envelope;
  if (!result || typeof result.image_uri !== 'string' || !result.image_uri.startsWith('https://')) {
    return null;
  }
  const labels: Record<string, string> = {
    regime_ribbon: 'Market regime ribbon',
    pfe_overlay: 'PFE overlay',
  };
  const role = typeof result.plot_role === 'string' ? result.plot_role : 'plot';
  return { src: result.image_uri, alt: labels[role] ?? 'Generated chart' };
}
```

In `ImageViewer`, track `failed` with `useState(false)`, render an `Alert` containing the plot name when failed, and set `onError={() => setFailed(true)}` on the image. Do not leave a broken-image element in the DOM. The happy path test asserts both images have `naturalWidth > 0`.

- [ ] **Step 6: Run frontend unit tests and build**

```bash
cd frontend
npm test -- --run
npm run build
```

- [ ] **Step 7: Commit Task 10**

```bash
git add frontend/src/api/stream.ts frontend/src/App.tsx frontend/src/components/ExposureSummary.tsx frontend/src/components/RunDetails.tsx frontend/src/components/DiagnosticsPanel.tsx frontend/src/components/ImageViewer.tsx frontend/tests/api/stream.test.ts frontend/tests/App.test.tsx frontend/tests/components/RunDetails.test.tsx frontend/tests/components/DiagnosticsPanel.test.tsx frontend/tests/e2e/happy_path.spec.ts
git commit -m "fix: render quantitative results from structured identity"
```

---

## Stage 7: Deployment And Reproducibility Proof

### Task 11: Add a live three-run acceptance verifier

**Files:**
- Create: `scripts/verify_live_reproducibility.py`
- Create: `tests/test_verify_live_reproducibility.py`
- Create: `docs/results/live_reproducibility.json`
- Modify: `docs/results/headline_calibration.json`
- Modify: `docs/runbook.md`

**Interfaces:**
- Consumes: deployed SSE endpoint and API key.
- Produces: raw per-run event logs and a machine-verifiable `live_reproducibility.json` acceptance record.

- [ ] **Step 1: Write failing verifier tests with recorded SSE fixtures**

The verifier must parse native SSE and fail unless all runs have:

- distinct `execution_id` values;
- one identical `spec_hash`;
- identical canonical parameters and pinned provenance;
- exactly one successful baseline, Chronos-only, and augmented exposure result;
- identical EE, PFE 97.5%, and ES 97.5% after decimal quantization to cents;
- valid artifact URIs and 64-character SHA-256 values;
- successful attribution, coverage status, regime plot, and PFE overlay with PNG hashes;
- zero failed tool lifecycle events.

Test a deliberately swapped event order and prove it passes. Test a one-cent metric difference, a missing Chronos-only result, a failed retry, a reused execution ID, and a provenance mismatch and prove each fails with a specific message.

- [ ] **Step 2: Run and confirm failure**

```bash
pytest tests/test_verify_live_reproducibility.py -v
```

- [ ] **Step 3: Implement the verifier**

Use `decimal.Decimal(str(value)).quantize(Decimal("0.01"))`; do not compare binary floats directly. The script accepts `--stream-url`, `--api-key`, `--runs 3`, `--prompt`, and `--output`. It issues independent requests, records raw event logs beside the summary, and exits non-zero on any acceptance failure.

Also compile these wording variants locally before live invocation and require the same `spec_hash`:

```text
As of 2022-09-30, use 1,260 trading days of history, simulate 252 trading days ahead with 500 paths per engine, and use a 0.5305 stress weight. Compare baseline and Chronos-2-augmented exposure.

Run the stage safe comparison on Sep 30 2022 with five trading years behind us and one trading year forward, 500 scenarios from each model, and 53.05 percent stress weighting.
```

Use this verifier core; unit tests call `verify_runs` with recorded event lists and mock `collect_events` for CLI tests:

```python
from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import uuid

import requests


ROLES = ("baseline", "chronos_only", "augmented")
METRICS = ("ee", "pfe_975", "es_975")


def collect_events(stream_url: str, api_key: str, prompt: str) -> list[dict[str, object]]:
    response = requests.get(
        stream_url,
        params={"session_id": str(uuid.uuid4()), "prompt": prompt},
        headers={"x-api-key": api_key},
        stream=True,
        timeout=(10, 900),
    )
    response.raise_for_status()
    events: list[dict[str, object]] = []
    data_lines: list[str] = []
    for line in response.iter_lines(decode_unicode=True):
        if line == "":
            if data_lines:
                events.append(json.loads("\n".join(data_lines)))
                data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data: "):
            data_lines.append(line[6:])
    if data_lines:
        events.append(json.loads("\n".join(data_lines)))
    return events


def _cent(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _tool_result(event: dict[str, object]) -> dict[str, object] | None:
    if event.get("type") != "tool" or event.get("status") != "done":
        return None
    envelope = event.get("result")
    if not isinstance(envelope, dict) or envelope.get("status") != "ok":
        return None
    result = envelope.get("result")
    return result if isinstance(result, dict) else None


def summarize_run(events: list[dict[str, object]]) -> dict[str, object]:
    stream_errors = [event for event in events if event.get("type") == "error"]
    if stream_errors:
        raise AssertionError(f"stream errors: {stream_errors}")
    failures = [event for event in events if event.get("type") == "tool" and event.get("status") == "failed"]
    if failures:
        raise AssertionError(f"failed tool lifecycle events: {failures}")
    specs = [event for event in events if event.get("type") == "run_spec"]
    if len(specs) != 1:
        raise AssertionError(f"expected one run_spec event, got {len(specs)}")
    exposures = {
        str(event["scenario_role"]): event
        for event in events
        if event.get("type") == "exposure_result"
    }
    if set(exposures) != set(ROLES):
        raise AssertionError(f"exposure roles differ: {sorted(exposures)}")
    diagnostics = [event for event in events if event.get("type") == "diagnostics"]
    if len(diagnostics) != 1:
        raise AssertionError(f"expected one diagnostics event, got {len(diagnostics)}")
    diagnostic_body = diagnostics[0].get("diagnostics")
    if not isinstance(diagnostic_body, dict):
        raise AssertionError("diagnostics payload is not an object")
    attribution = diagnostic_body.get("attribution")
    expected_distributions = {
        "uniform_parametric", "uniform_chronos", "reweighted_parametric",
        "reweighted_chronos", "final_blend",
    }
    if not isinstance(attribution, dict) or set(attribution) != expected_distributions:
        raise AssertionError("attribution does not contain all five distributions")
    for coverage_name in ("portfolio_coverage", "factor_coverage"):
        coverage = diagnostic_body.get(coverage_name)
        if not isinstance(coverage, dict) or coverage.get("available") is not True:
            raise AssertionError(f"{coverage_name} is unavailable")
        if set(coverage.get("results", {})) != set(ROLES):
            raise AssertionError(f"{coverage_name} does not contain all three roles")
    factor_results = diagnostic_body["factor_coverage"]["results"]
    for role in ROLES:
        if len(factor_results[role].get("per_series", {})) != 21:
            raise AssertionError(f"factor_coverage for {role} does not contain 21 series")

    plots: dict[str, dict[str, object]] = {}
    for event in events:
        if event.get("name") != "plot":
            continue
        result = _tool_result(event)
        if result and result.get("plot_role") in {"regime_ribbon", "pfe_overlay"}:
            plots[str(result["plot_role"])] = result
    if set(plots) != {"regime_ribbon", "pfe_overlay"}:
        raise AssertionError(f"plot roles differ: {sorted(plots)}")

    for role, event in exposures.items():
        if len(str(event.get("paths_sha256", ""))) != 64:
            raise AssertionError(f"{role} paths hash is invalid")
        if len(str(event.get("metrics_sha256", ""))) != 64:
            raise AssertionError(f"{role} metrics hash is invalid")
    for role, result in plots.items():
        if len(str(result.get("image_sha256", ""))) != 64:
            raise AssertionError(f"{role} image hash is invalid")
        if not str(result.get("image_s3_uri", "")).startswith("s3://"):
            raise AssertionError(f"{role} stable image URI is invalid")
        if not str(result.get("image_uri", "")).startswith("https://"):
            raise AssertionError(f"{role} browser image URI is not HTTPS")

    run_spec = specs[0]["run_spec"]
    return {
        "execution_id": specs[0]["execution_id"],
        "spec_hash": specs[0]["spec_hash"],
        "run_spec": run_spec,
        "terminal": {
            role: {metric: exposures[role]["terminal"][metric] for metric in METRICS}
            for role in ROLES
        },
        "diagnostics": diagnostic_body,
        "plots": plots,
    }


def verify_runs(event_runs: list[list[dict[str, object]]]) -> list[dict[str, object]]:
    if len(event_runs) != 3:
        raise AssertionError(f"expected three independent runs, got {len(event_runs)}")
    summaries = [summarize_run(events) for events in event_runs]
    execution_ids = {str(item["execution_id"]) for item in summaries}
    if len(execution_ids) != 3:
        raise AssertionError("execution_id values are not distinct")
    spec_hashes = {str(item["spec_hash"]) for item in summaries}
    if len(spec_hashes) != 1:
        raise AssertionError("spec_hash values differ")
    provenance = [item["run_spec"]["provenance"] for item in summaries]
    if provenance[1:] != provenance[:-1]:
        raise AssertionError("run provenance differs")
    canonical_specs = []
    for item in summaries:
        canonical = dict(item["run_spec"])
        canonical.pop("execution_id", None)
        canonical.pop("spec_hash", None)
        canonical_specs.append(canonical)
    if canonical_specs[1:] != canonical_specs[:-1]:
        raise AssertionError("canonical RunSpec values differ")
    reference = summaries[0]["terminal"]
    for index, summary in enumerate(summaries[1:], start=2):
        for role in ROLES:
            for metric in METRICS:
                expected = _cent(reference[role][metric])
                actual = _cent(summary["terminal"][role][metric])
                if actual != expected:
                    raise AssertionError(
                        f"run {index} {role}.{metric} differs: {actual} != {expected}"
                    )
    return summaries
```

`main()` loops exactly `args.runs` times, writes each raw event list to `<output stem>-run-1.events.json` through `-run-3.events.json`, calls `verify_runs`, and writes the accepted summaries plus `status: "passed"` to `args.output`. It rejects `--runs` values other than `3` for the production acceptance command.

- [ ] **Step 4: Document exact deployment and rollback gates**

Update the runbook in this order:

1. Run every local test suite.
2. Build baseline, Chronos, and AgentCore images with Finch and immutable git-SHA tags.
3. Push and resolve ECR image digests.
4. Deploy tool/shared layers and Gateway schema changes.
5. Deploy Fargate task definitions.
6. Deploy AgentCore runtime with pinned provenance environment values.
7. Deploy `Frontend --exclusively`, rebuild from `.env.production`, then deploy `Api --exclusively` as required by the existing export-deadlock workaround.
8. Preserve the Function URL `AWS_IAM`, CloudFront OAC dual Lambda permissions, WAF, disabled cache, and forwarded `x-api-key`.
9. Run one smoke prompt and inspect tool lifecycle failures before the three-run gate.
10. Run the shared calibration script against the deployed endpoint with the same profile and provenance.
11. Run the verifier and Playwright browser assertions.

Document the previous image/task-definition revisions needed for rollback. Do not retag `latest` as the only provenance record.

- [ ] **Step 5: Run verifier unit tests**

```bash
pytest tests/test_verify_live_reproducibility.py -v
```

- [ ] **Step 6: Commit Task 11 before deployment**

```bash
git add scripts/verify_live_reproducibility.py tests/test_verify_live_reproducibility.py docs/runbook.md
git commit -m "test: add live quantitative reproducibility gate"
```

- [ ] **Step 7: Run the complete local verification matrix**

```bash
pytest -q
pytest tools/tests agent/tests -q
node --test tools/lambda/sse_relay/protocol.test.mjs
```

```bash
cd infra
npm test -- --runInBand
npm run build
```

```bash
cd frontend
npm test -- --run
npm run build
```

Expected: all suites pass. Record counts in the deployment log; do not rely on the historical counts in `AGENTS.md`.

- [ ] **Step 8: Build, push, and deploy with Finch**

Follow `docs/runbook.md` exactly. Capture immutable image tags and resolved digests in the deployed RunSpec provenance. Stop immediately on any failed CloudFormation resource, unhealthy AgentCore endpoint, failed ECS task, relay 4xx/5xx, or frontend smoke test.

- [ ] **Step 9: Execute the exact prompt three independent times**

```bash
python scripts/verify_live_reproducibility.py \
  --stream-url "$STREAM_URL" \
  --api-key "$API_KEY" \
  --runs 3 \
  --prompt "Run the stage-safe headline demo for September 30, 2022. Use five years of trading history, project one trading year into the future, and generate 500 scenarios with each engine. Apply a 53.05% stress weight. Show the market regime and compare baseline exposure with Chronos-2-augmented exposure. Report the final EE, 97.5% PFE, 97.5% ES, and the PFE change." \
  --output docs/results/live_reproducibility.json
```

The command passes only if the three independent executions are identical to the cent under equivalent provenance. It must not bless the first result as expected and compare only labels; all raw structured metrics and hashes are checked.

- [ ] **Step 10: Run the aligned calibration path**

Run `scripts/calibrate_headline.py --profile stage_safe_headline_v1` against the same deployed endpoint and provenance used by the live runs. Write `docs/results/headline_calibration.json`. Compare its baseline, Chronos-only, and augmented terminal metrics with the structured metrics from one live execution at cent precision. Any mismatch blocks acceptance and must be traced to an input, model, book, blend, pricing, or serialization difference; do not update an expected number to make the gate pass.

- [ ] **Step 11: Run live wording variants and browser verification**

Run each equivalent prompt once and require the same `spec_hash` and cent-level results. Run one ambiguous prompt and verify it asks for clarification without any `tool_start` event.

Use Playwright at desktop and mobile widths to verify:

- text streams incrementally;
- tool lifecycle events update while the run is active;
- baseline, Chronos-only, and augmented rows populate from structured events;
- attribution and coverage render;
- regime ribbon and PFE overlay load in the browser;
- no literal `\\n`, fenced JSON dependency, broken image icon, overlap, or horizontal clipping appears.

- [ ] **Step 12: Commit measured live evidence**

```bash
git add docs/results/live_reproducibility.json docs/results/headline_calibration.json
git commit -m "docs: record live reproducibility acceptance"
```

---

## Final Acceptance Checklist

- [ ] Equivalent supported prompts compile to one `spec_hash` without model inference.
- [ ] Independent executions have distinct `execution_id` values.
- [ ] Ambiguous quantitative prompts fail closed before any tool call.
- [ ] Supported quantitative requests execute one fixed MCP tool DAG; the model cannot omit, add, or reorder calculations.
- [ ] Live and calibration use one RunSpec, one exact panel/covariate slice, one book, one blend implementation, and one diagnostics implementation.
- [ ] Baseline and Chronos use the same 1,260-row history and 252-day horizon for the stage-safe profile.
- [ ] Every stochastic seed and deployed implementation version is explicit provenance.
- [ ] All artifacts carry execution identity, spec identity, source identity, and content hashes.
- [ ] `price_book` labels baseline, Chronos-only, and augmented from `PathSet.source` regardless of invocation order.
- [ ] Chronos-only contribution is reported separately from component reweighting and final blending.
- [ ] Portfolio PFE coverage and 21-factor central-band coverage are measured on strictly held-out observations or explicitly marked unavailable.
- [ ] Structured SSE, not model markers or fenced JSON, populates run details, exposure, diagnostics, tool trace, and plots.
- [ ] Existing streaming edge security and nine-tool architecture remain intact.
- [ ] Core, tool, agent, relay, CDK, frontend, and Playwright checks pass.
- [ ] Three exact live prompt executions match to the cent with identical provenance and no failed tools.
