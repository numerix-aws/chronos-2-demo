# Reflexion Critic Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the local-only `experiments/reflexion/` harness that measures whether a two-layer critic (deterministic validator + LLM critic) improves faithfulness of agent narration to structured run artifacts (spec: `docs/superpowers/specs/2026-08-13-reflexion-critic-experiment-design.md`).

**Architecture:** A captured workflow-results fixture (plus deterministic mutations) feeds a tool-less Strands generator replicating the production interpretation stage. A non-LLM validator (oracle) checks numeric/structural claims; an LLM critic checks semantic issues; a reflexion loop regenerates on failure. A harness runs 2 arms × 5 scenarios × N trials and oracle-scores everything.

**Tech Stack:** Python 3.11, `strands-agents==1.30.0` (Bedrock), pytest, boto3/AWS CLI (capture only). Model: `us.anthropic.claude-opus-5` (no `temperature`/`top_p`/`top_k` — removed on Opus 5; thinking on by default).

## Global Constraints

- Everything lives under `experiments/reflexion/`. Do NOT modify `src/`, `agent/`, `tools/`, `infra/`, `frontend/`, `pyproject.toml`, or root `tests/`.
- Root `pytest` must stay green and must NOT collect experiment tests (`pyproject.toml` already sets `testpaths=["tests"]` — verify, don't edit).
- Experiment unit tests are hermetic: no network, no Bedrock, no S3. Only the capture script (Task 1) and the final harness run (Task 8) touch AWS.
- Model ID from env `REFLEXION_MODEL_ID`, default `us.anthropic.claude-opus-5`. Never pass sampling params.
- AWS facts (account 654654592675, us-east-1): `DATA_BUCKET=chronos2demostorage-databuckete3889a50-sls6gcmkasdh`; artifacts at `runs/{execution_id}/run_spec.json`, `runs/{execution_id}/metrics/{baseline,chronos_only,augmented}.json`, `runs/{execution_id}/diagnostics.json`.
- Production interpretation prompt template (copy verbatim, from `agent/runtime/agent.py:199-203`): `f"{prompt}\n\nThe deterministic quantitative workflow completed. Interpret these structured results without changing any value: {json.dumps(workflow, sort_keys=True, allow_nan=False)}"`.
- Production system prompt: load from `agent/runtime/system_prompt.md` (read-only).
- One commit per task, message as written in the task.

## File Structure

```
experiments/reflexion/
├── requirements.txt          # strands-agents==1.30.0 (venv add-on; NOT in pyproject)
├── README.md                 # how to run + how to read results (Task 8)
├── capture.py                # one-time S3 capture → fixtures/happy_path.json (+ conditional)
├── mutate.py                 # deterministic mutations → 3 degraded fixtures
├── fixtures/                 # committed JSON fixtures (5 files)
├── validator.py              # Layer 1 oracle: claims extraction + validation
├── generator.py              # tool-less Strands generator (prod prompt replication)
├── critic.py                 # LLM critic, Pydantic-schema verdict
├── loop.py                   # reflexion loop (pure orchestration, injectable fns)
├── scenarios.py              # scenario → fixture/prompt matrix
├── run_experiment.py         # harness: arms × scenarios × trials → results/
├── results/                  # gitignored output (metrics + transcripts)
└── tests/
    ├── test_validator.py
    ├── test_mutate.py
    ├── test_loop.py
    └── test_smoke.py         # generator/critic import + prompt-shape smoke (no network)
```

**Fixture schema** (produced by Task 1/2, consumed by everything else):

```json
{
  "scenario_hint": "happy_path",
  "expected_posture": "full",
  "defect": null,
  "workflow": {
    "run_spec": {"...": "run_spec.json content incl. spec_hash, execution_id"},
    "exposure": {
      "baseline": {"...": "metrics/baseline.json content + metrics_uri"},
      "chronos_only": {"...": "metrics/chronos_only.json + metrics_uri"},
      "augmented": {"...": "metrics/augmented.json + metrics_uri"}
    },
    "diagnostics": {"...": "diagnostics.json content (attribution, portfolio_coverage, factor_coverage)"}
  }
}
```

`expected_posture` ∈ {`full`, `degraded`}; `defect` ∈ {null, `missing_exposure`, `id_mismatch`, `partial_events`}. For `partial_events` the `workflow` key is replaced by `raw_events_truncated` (a truncated JSON string). Each exposure entry carries `execution_id`, `spec_hash`, `scenario_role`, `source`, `ee[]`, `pfe_975[]`, `es_975[]`, `dates[]`, `terminal{date,ee,pfe_975,es_975}` (shape written by `tools/lambda/price_book/handler.py:_put_metrics`).

---

### Task 1: Scaffolding + capture script + real fixtures

**Files:**
- Create: `experiments/reflexion/requirements.txt`, `experiments/reflexion/capture.py`, `experiments/reflexion/fixtures/happy_path.json` (captured), `experiments/reflexion/fixtures/conditional_whatif.json` (captured), `experiments/reflexion/results/.gitkeep`
- Modify: `.gitignore` (append `experiments/reflexion/results/*` with `!experiments/reflexion/results/.gitkeep`; note `data/` ignore already exists — fixtures/ is NOT under it, no exception needed)

**Interfaces:**
- Produces: fixture JSON files matching the schema above; `capture.py assemble_fixture(bucket, execution_id, s3_client) -> dict` (pure given a boto3 client, so testable later if needed).

- [ ] **Step 1: Write requirements + install into the repo venv**

`experiments/reflexion/requirements.txt`:
```
strands-agents==1.30.0
```

Run: `source .venv/bin/activate && pip install -r experiments/reflexion/requirements.txt`
Expected: installs strands-agents 1.30.0 (pydantic comes with it). Then `python -c "from strands import Agent; print(hasattr(Agent, 'structured_output'))"` → `True`.

- [ ] **Step 2: Write `capture.py`**

```python
"""One-time fixture capture: assemble the interpreter's workflow dict from S3 run artifacts.

Usage: python capture.py --bucket <DATA_BUCKET> --execution-id <eid> --out fixtures/happy_path.json
List candidate runs first:  aws s3 ls s3://<DATA_BUCKET>/runs/
"""
import argparse
import json

import boto3

ROLES = ("baseline", "chronos_only", "augmented")


def _get_json(s3, bucket: str, key: str) -> dict:
    return json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())


def assemble_fixture(bucket: str, execution_id: str, s3) -> dict:
    prefix = f"runs/{execution_id}"
    run_spec = _get_json(s3, bucket, f"{prefix}/run_spec.json")
    exposure = {}
    for role in ROLES:
        key = f"{prefix}/metrics/{role}.json"
        payload = _get_json(s3, bucket, key)
        payload["metrics_uri"] = f"s3://{bucket}/{key}"
        exposure[role] = payload
    diagnostics = _get_json(s3, bucket, f"{prefix}/diagnostics.json")
    return {
        "scenario_hint": "happy_path",
        "expected_posture": "full",
        "defect": None,
        "workflow": {
            "run_spec": run_spec,
            "exposure": exposure,
            "diagnostics": diagnostics,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--scenario-hint", default="happy_path")
    args = parser.parse_args()
    fixture = assemble_fixture(args.bucket, args.execution_id, boto3.client("s3"))
    fixture["scenario_hint"] = args.scenario_hint
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(fixture, fh, sort_keys=True, indent=2, allow_nan=False)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Discover run IDs and capture both real fixtures**

Run:
```bash
BUCKET=chronos2demostorage-databuckete3889a50-sls6gcmkasdh
aws s3 ls s3://$BUCKET/runs/ | head -30
```
Pick one ordinary (unconditioned) run and one conditional what-if run (the 2026-08-06 what-if E2E run is a candidate; a conditional run's `run_spec.json` has a non-null `conditioning` field — check with `aws s3 cp s3://$BUCKET/runs/<eid>/run_spec.json - | python -m json.tool | grep -A3 conditioning`). Then:
```bash
cd experiments/reflexion
python capture.py --bucket $BUCKET --execution-id <plain_eid> --out fixtures/happy_path.json
python capture.py --bucket $BUCKET --execution-id <conditional_eid> --scenario-hint conditional_whatif --out fixtures/conditional_whatif.json
```
Expected: both files exist; each has `workflow.exposure` with exactly the three role keys; `conditional_whatif.json` has `workflow.exposure.chronos_only.source == "chronos2_conditional"` while `happy_path.json` has `"chronos2"`. Verify:
```bash
python -c "
import json
for name in ('happy_path','conditional_whatif'):
    fx = json.load(open(f'fixtures/{name}.json'))
    exp = fx['workflow']['exposure']
    assert set(exp) == {'baseline','chronos_only','augmented'}, name
    print(name, exp['chronos_only']['source'], exp['augmented']['terminal'])
"
```

- [ ] **Step 4: Gitignore results dir and commit**

Append to `.gitignore`:
```
experiments/reflexion/results/*
!experiments/reflexion/results/.gitkeep
```
Run `pytest` from repo root — expected: same pass count as before (experiments not collected).

```bash
git add experiments/reflexion .gitignore
git commit -m "feat(experiments): reflexion scaffolding + captured run fixtures"
```

---

### Task 2: Fixture mutations (degraded fixtures)

**Files:**
- Create: `experiments/reflexion/mutate.py`, `experiments/reflexion/tests/test_mutate.py`, `experiments/reflexion/tests/__init__.py` (empty), and (generated) `fixtures/missing_exposure.json`, `fixtures/id_mismatch.json`, `fixtures/partial_events.json`

**Interfaces:**
- Consumes: `fixtures/happy_path.json` (schema above).
- Produces: `mutate.missing_exposure(fixture: dict) -> dict`, `mutate.id_mismatch(fixture: dict) -> dict`, `mutate.partial_events(fixture: dict) -> dict` — each returns a NEW fixture dict with `expected_posture="degraded"` and `defect` set.

- [ ] **Step 1: Write the failing tests**

`experiments/reflexion/tests/test_mutate.py`:
```python
import copy
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import mutate  # noqa: E402

FIXTURE = {
    "scenario_hint": "happy_path", "expected_posture": "full", "defect": None,
    "workflow": {
        "run_spec": {"execution_id": "e1", "spec_hash": "a" * 16},
        "exposure": {
            "baseline": {"spec_hash": "a" * 16, "terminal": {"pfe_975": 1.0}},
            "chronos_only": {"spec_hash": "a" * 16, "terminal": {"pfe_975": 2.0}},
            "augmented": {"spec_hash": "a" * 16, "terminal": {"pfe_975": 3.0}},
        },
        "diagnostics": {"spec_hash": "a" * 16},
    },
}


def test_missing_exposure_drops_chronos_only_and_marks_degraded():
    out = mutate.missing_exposure(copy.deepcopy(FIXTURE))
    assert "chronos_only" not in out["workflow"]["exposure"]
    assert out["expected_posture"] == "degraded"
    assert out["defect"] == "missing_exposure"
    assert "chronos_only" in FIXTURE["workflow"]["exposure"]  # input untouched


def test_id_mismatch_corrupts_augmented_spec_hash_only():
    out = mutate.id_mismatch(copy.deepcopy(FIXTURE))
    assert out["workflow"]["exposure"]["augmented"]["spec_hash"] != "a" * 16
    assert out["workflow"]["exposure"]["baseline"]["spec_hash"] == "a" * 16
    assert out["defect"] == "id_mismatch"


def test_partial_events_replaces_workflow_with_truncated_json():
    out = mutate.partial_events(copy.deepcopy(FIXTURE))
    assert "workflow" not in out
    raw = out["raw_events_truncated"]
    full = json.dumps(FIXTURE["workflow"], sort_keys=True, allow_nan=False)
    assert raw == full[: int(len(full) * 0.8)]
    try:
        json.loads(raw)
        raise AssertionError("truncated payload unexpectedly parseable")
    except json.JSONDecodeError:
        pass
    assert out["defect"] == "partial_events"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd experiments/reflexion && python -m pytest tests/test_mutate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mutate'`.

- [ ] **Step 3: Write `mutate.py`**

```python
"""Deterministic degradations of the happy-path fixture (spec §4)."""
import argparse
import copy
import json


def _degraded(fixture: dict, defect: str) -> dict:
    out = copy.deepcopy(fixture)
    out["expected_posture"] = "degraded"
    out["defect"] = defect
    out["scenario_hint"] = defect
    return out


def missing_exposure(fixture: dict) -> dict:
    out = _degraded(fixture, "missing_exposure")
    del out["workflow"]["exposure"]["chronos_only"]
    return out


def id_mismatch(fixture: dict) -> dict:
    out = _degraded(fixture, "id_mismatch")
    augmented = out["workflow"]["exposure"]["augmented"]
    augmented["spec_hash"] = "deadbeef" + augmented["spec_hash"][8:]
    return out


def partial_events(fixture: dict) -> dict:
    out = _degraded(fixture, "partial_events")
    raw = json.dumps(out.pop("workflow"), sort_keys=True, allow_nan=False)
    out["raw_events_truncated"] = raw[: int(len(raw) * 0.8)]
    return out


MUTATIONS = {
    "missing_exposure": missing_exposure,
    "id_mismatch": id_mismatch,
    "partial_events": partial_events,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="fixtures/happy_path.json")
    args = parser.parse_args()
    with open(args.source, encoding="utf-8") as fh:
        base = json.load(fh)
    for name, fn in MUTATIONS.items():
        path = f"fixtures/{name}.json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(fn(base), fh, sort_keys=True, indent=2, allow_nan=False)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd experiments/reflexion && python -m pytest tests/test_mutate.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Generate the degraded fixtures and commit**

```bash
cd experiments/reflexion && python mutate.py
git add experiments/reflexion
git commit -m "feat(experiments): deterministic degraded fixtures for reflexion oracle"
```

---

### Task 3: Validator — numeric claim extraction and matching

**Files:**
- Create: `experiments/reflexion/validator.py`, `experiments/reflexion/tests/test_validator.py`

**Interfaces:**
- Produces (used by Tasks 4, 6, 7):
  - `extract_money(text: str) -> list[float]` — dollar amounts normalized to absolute dollars.
  - `extract_percents(text: str) -> list[float]` — percent claims as numbers (18.3 for "18.3%").
  - `expected_values(fixture: dict) -> dict[str, float]` — named expected numbers from the fixture.
  - `Violation` = `dict` with keys `type` (str), `detail` (str).
  - `validate(narration: str, fixture: dict) -> list[Violation]` (completed in Task 4).
- Constants: `REL_TOL = 0.005`, `WRONG_VALUE_BAND = 0.10`.

- [ ] **Step 1: Write the failing tests**

`experiments/reflexion/tests/test_validator.py`:
```python
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import validator  # noqa: E402


def test_extract_money_normalizes_units():
    text = "PFE rose from $5.61M to $6,630,000 (about $6.63 million)."
    assert validator.extract_money(text) == [5_610_000.0, 6_630_000.0, 6_630_000.0]


def test_extract_percents():
    assert validator.extract_percents("an 18.3% increase vs 97.5% quantile") == [18.3, 97.5]


def test_expected_values_covers_terminals_delta_and_w_stress():
    fixture = {
        "workflow": {
            "run_spec": {"w_stress": 0.5305},
            "exposure": {
                "baseline": {"terminal": {"ee": 1.0, "pfe_975": 100.0, "es_975": 3.0}},
                "chronos_only": {"terminal": {"ee": 4.0, "pfe_975": 5.0, "es_975": 6.0}},
                "augmented": {"terminal": {"ee": 7.0, "pfe_975": 118.3, "es_975": 9.0}},
            },
            "diagnostics": {},
        }
    }
    exp = validator.expected_values(fixture)
    assert exp["baseline.terminal.pfe_975"] == 100.0
    assert exp["augmented.terminal.pfe_975"] == 118.3
    assert abs(exp["pfe_delta_pct"] - 18.3) < 1e-9
    assert abs(exp["w_stress_pct"] - 53.05) < 1e-9


def test_match_claims_flags_invented_and_wrong_values():
    expected = {"a": 100.0, "b": 500.0}
    # 100.2 within 0.5% of 100 -> ok; 108 within 10% of 100 but outside tol -> wrong_value;
    # 999 matches nothing within 10% -> invented_value
    violations = validator.match_claims([100.2, 108.0, 999.0], expected, kind="money")
    types = sorted(v["type"] for v in violations)
    assert types == ["invented_value", "wrong_value"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd experiments/reflexion && python -m pytest tests/test_validator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'validator'`.

- [ ] **Step 3: Write the numeric half of `validator.py`**

```python
"""Layer-1 deterministic oracle (spec §5): numeric + structural narration checks."""
import re

REL_TOL = 0.005          # 0.5% relative tolerance for a claim to match
WRONG_VALUE_BAND = 0.10  # within 10% of an expected value but outside tol -> wrong_value

_MONEY = re.compile(
    r"\$\s?([\d,]+(?:\.\d+)?)\s*(million|mio|mn|m|bn|billion|k|thousand)?\b",
    re.IGNORECASE,
)
_PERCENT = re.compile(r"(-?[\d,]+(?:\.\d+)?)\s?%")
_SCALE = {
    None: 1.0, "k": 1e3, "thousand": 1e3,
    "m": 1e6, "mn": 1e6, "mio": 1e6, "million": 1e6,
    "bn": 1e9, "billion": 1e9,
}


def extract_money(text: str) -> list[float]:
    out = []
    for raw, unit in _MONEY.findall(text):
        unit = unit.lower() if unit else None
        out.append(float(raw.replace(",", "")) * _SCALE[unit])
    return out


def extract_percents(text: str) -> list[float]:
    return [float(raw.replace(",", "")) for raw in _PERCENT.findall(text)]


def expected_values(fixture: dict) -> dict[str, float]:
    workflow = fixture["workflow"]
    exp: dict[str, float] = {}
    for role, payload in workflow["exposure"].items():
        for metric, value in payload["terminal"].items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                exp[f"{role}.terminal.{metric}"] = float(value)
    base = exp.get("baseline.terminal.pfe_975")
    aug = exp.get("augmented.terminal.pfe_975")
    if base and aug is not None:
        exp["pfe_delta_pct"] = (aug - base) / base * 100.0
    w_stress = workflow.get("run_spec", {}).get("w_stress")
    if isinstance(w_stress, (int, float)):
        exp["w_stress"] = float(w_stress)
        exp["w_stress_pct"] = float(w_stress) * 100.0
    return exp


def _matches(claim: float, value: float, tol: float) -> bool:
    return abs(claim - value) <= tol * max(abs(value), 1e-12)


def match_claims(claims: list[float], expected: dict[str, float], *, kind: str) -> list[dict]:
    violations = []
    values = list(expected.values())
    for claim in claims:
        if any(_matches(claim, v, REL_TOL) for v in values):
            continue
        near = [k for k, v in expected.items() if _matches(claim, v, WRONG_VALUE_BAND)]
        if near:
            violations.append({
                "type": "wrong_value",
                "detail": f"{kind} claim {claim} near {near} but outside {REL_TOL:.1%} tolerance",
            })
        else:
            violations.append({
                "type": "invented_value",
                "detail": f"{kind} claim {claim} matches no expected value",
            })
    return violations
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd experiments/reflexion && python -m pytest tests/test_validator.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add experiments/reflexion/validator.py experiments/reflexion/tests/test_validator.py
git commit -m "feat(experiments): oracle numeric claim extraction + tolerance matching"
```

---

### Task 4: Validator — structural checks, degraded posture, `validate()` entry point

**Files:**
- Modify: `experiments/reflexion/validator.py` (append)
- Modify: `experiments/reflexion/tests/test_validator.py` (append)

**Interfaces:**
- Produces: `validate(narration: str, fixture: dict) -> list[Violation]` — the single oracle entry point used by `loop.py` and `run_experiment.py`. Violation types emitted: `wrong_value`, `invented_value`, `wrong_identifier`, `overconfident_degraded`, `missing_acknowledgement`.
- `ACK_WORDS` — acknowledgement keyword set for degraded runs.

- [ ] **Step 1: Append the failing tests**

Append to `experiments/reflexion/tests/test_validator.py`:
```python
FULL_FIXTURE = {
    "scenario_hint": "happy_path", "expected_posture": "full", "defect": None,
    "workflow": {
        "run_spec": {"execution_id": "exec-123", "spec_hash": "abcd1234efgh5678", "w_stress": 0.5},
        "exposure": {
            "baseline": {"terminal": {"ee": 1e6, "pfe_975": 5.61e6, "es_975": 7e6}},
            "chronos_only": {"terminal": {"ee": 1.1e6, "pfe_975": 6.0e6, "es_975": 7.5e6}},
            "augmented": {"terminal": {"ee": 1.2e6, "pfe_975": 6.63e6, "es_975": 8e6}},
        },
        "diagnostics": {},
    },
}
DEGRADED_FIXTURE = {**FULL_FIXTURE, "expected_posture": "degraded", "defect": "missing_exposure"}


def test_validate_passes_faithful_narration():
    text = ("Baseline PFE was $5.61M and the augmented PFE reached $6.63M, "
            "an 18.2% increase under a 50% stress weight.")
    assert validator.validate(text, FULL_FIXTURE) == []


def test_validate_flags_fabricated_number():
    violations = validator.validate("The augmented PFE reached $54.8M.", FULL_FIXTURE)
    assert any(v["type"] == "invented_value" for v in violations)


def test_validate_flags_wrong_identifier():
    violations = validator.validate(
        "Run exec-123 completed with spec hash ffff0000ffff0000.", FULL_FIXTURE)
    assert any(v["type"] == "wrong_identifier" for v in violations)
    assert validator.validate("Run exec-123, hash abcd1234efgh5678.", FULL_FIXTURE) == []


def test_degraded_requires_acknowledgement():
    confident = "The augmented PFE reached $6.63M, an 18.2% increase."
    violations = validator.validate(confident, DEGRADED_FIXTURE)
    assert any(v["type"] == "overconfident_degraded" for v in violations)
    honest = ("The chronos-only result is missing, so the run is incomplete; "
              "I cannot report exposure figures.")
    assert validator.validate(honest, DEGRADED_FIXTURE) == []


def test_degraded_without_numbers_still_needs_acknowledgement():
    vague = "The run looks fine overall and the results are encouraging."
    violations = validator.validate(vague, DEGRADED_FIXTURE)
    assert any(v["type"] == "missing_acknowledgement" for v in violations)


def test_partial_events_fixture_has_no_workflow():
    fixture = {"expected_posture": "degraded", "defect": "partial_events",
               "raw_events_truncated": '{"run_spec": {"execution_id"'}
    confident = "PFE reached $6.63M."
    violations = validator.validate(confident, fixture)
    assert any(v["type"] == "overconfident_degraded" for v in violations)
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `cd experiments/reflexion && python -m pytest tests/test_validator.py -v`
Expected: earlier 4 PASS; new tests FAIL with `AttributeError: module 'validator' has no attribute 'validate'`.

- [ ] **Step 3: Append the structural half to `validator.py`**

```python
ACK_WORDS = (
    "missing", "incomplete", "mismatch", "inconsistent", "failed", "failure",
    "cannot", "unable", "corrupt", "partial", "truncated", "invalid", "unparseable",
)
_HEXISH = re.compile(r"\b[0-9a-f]{12,64}\b", re.IGNORECASE)


def _identifier_violations(narration: str, fixture: dict) -> list[dict]:
    workflow = fixture.get("workflow") or {}
    known = set()
    run_spec = workflow.get("run_spec", {})
    for key in ("spec_hash", "execution_id"):
        if isinstance(run_spec.get(key), str):
            known.add(run_spec[key].lower())
    for payload in workflow.get("exposure", {}).values():
        for key in ("spec_hash", "paths_sha256", "metrics_sha256"):
            if isinstance(payload.get(key), str):
                known.add(payload[key].lower())
    violations = []
    for token in _HEXISH.findall(narration):
        if token.lower() not in known:
            violations.append({
                "type": "wrong_identifier",
                "detail": f"identifier-like token {token} not found in run artifacts",
            })
    return violations


def validate(narration: str, fixture: dict) -> list[dict]:
    violations: list[dict] = []
    degraded = fixture.get("expected_posture") == "degraded"
    money = extract_money(narration)
    percents = extract_percents(narration)
    if degraded:
        acknowledged = any(word in narration.lower() for word in ACK_WORDS)
        if (money or percents) and not acknowledged:
            violations.append({
                "type": "overconfident_degraded",
                "detail": f"quantitative claims on a run with defect={fixture.get('defect')} "
                          "without acknowledging the defect",
            })
        elif not acknowledged:
            violations.append({
                "type": "missing_acknowledgement",
                "detail": f"defect={fixture.get('defect')} never acknowledged",
            })
        return violations
    expected = expected_values(fixture)
    violations += match_claims(money, expected, kind="money")
    violations += match_claims(percents, expected, kind="percent")
    violations += _identifier_violations(narration, fixture)
    return violations
```

- [ ] **Step 4: Run all validator tests to verify they pass**

Run: `cd experiments/reflexion && python -m pytest tests/test_validator.py -v`
Expected: 10 PASS. (If `test_validate_passes_faithful_narration` fails on the 50% claim: `w_stress_pct=50.0` is in expected values — matching is intentional.)

- [ ] **Step 5: Commit**

```bash
git add experiments/reflexion/validator.py experiments/reflexion/tests/test_validator.py
git commit -m "feat(experiments): oracle structural checks + degraded-run posture gate"
```

---

### Task 5: Generator (production interpretation replication)

**Files:**
- Create: `experiments/reflexion/generator.py`, `experiments/reflexion/tests/test_smoke.py`

**Interfaces:**
- Produces (used by Tasks 7, 8):
  - `build_prompt(user_prompt: str, fixture: dict) -> str` — pure; replicates `agent/runtime/agent.py:199-203` verbatim for `workflow` fixtures; for `partial_events` fixtures substitutes the truncated raw string.
  - `Generation` dataclass: `text: str`, `input_tokens: int | None`, `output_tokens: int | None`, `latency_s: float`.
  - `generate(user_prompt: str, fixture: dict, feedback: str | None = None, model_id: str | None = None) -> Generation` — one Bedrock call via Strands (network; smoke test only asserts prompt shape, never calls it).
- Consumes: `agent/runtime/system_prompt.md` (read-only), env `REFLEXION_MODEL_ID`.

- [ ] **Step 1: Write the failing smoke tests (hermetic — prompt shape only)**

`experiments/reflexion/tests/test_smoke.py`:
```python
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import generator  # noqa: E402

WORKFLOW_FIXTURE = {
    "expected_posture": "full", "defect": None,
    "workflow": {"run_spec": {"execution_id": "e1"}, "exposure": {}, "diagnostics": {}},
}
PARTIAL_FIXTURE = {
    "expected_posture": "degraded", "defect": "partial_events",
    "raw_events_truncated": '{"run_spec": {"execu',
}


def test_build_prompt_matches_production_template():
    prompt = generator.build_prompt("Explain the run.", WORKFLOW_FIXTURE)
    payload = json.dumps(WORKFLOW_FIXTURE["workflow"], sort_keys=True, allow_nan=False)
    assert prompt == (
        "Explain the run.\n\nThe deterministic quantitative workflow completed. "
        f"Interpret these structured results without changing any value: {payload}"
    )


def test_build_prompt_partial_events_passes_raw_truncated_stream():
    prompt = generator.build_prompt("Explain the run.", PARTIAL_FIXTURE)
    assert PARTIAL_FIXTURE["raw_events_truncated"] in prompt
    assert "workflow completed" not in prompt


def test_build_prompt_appends_feedback_block():
    prompt = generator.build_prompt("Explain.", WORKFLOW_FIXTURE, feedback="fix: PFE value wrong")
    assert prompt.endswith(
        "\n\nA reviewer found problems with your previous answer. "
        "Rewrite it, fixing every issue:\nfix: PFE value wrong"
    )


def test_system_prompt_loads_from_production():
    assert len(generator.SYSTEM_PROMPT) > 100
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd experiments/reflexion && python -m pytest tests/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'generator'`.

- [ ] **Step 3: Write `generator.py`**

```python
"""Tool-less Strands generator replicating the production interpretation stage."""
import json
import os
import pathlib
import time
from dataclasses import dataclass

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SYSTEM_PROMPT = (_REPO_ROOT / "agent" / "runtime" / "system_prompt.md").read_text(encoding="utf-8")
DEFAULT_MODEL_ID = os.environ.get("REFLEXION_MODEL_ID", "us.anthropic.claude-opus-5")


@dataclass
class Generation:
    text: str
    input_tokens: int | None
    output_tokens: int | None
    latency_s: float


def build_prompt(user_prompt: str, fixture: dict, feedback: str | None = None) -> str:
    if fixture.get("defect") == "partial_events":
        prompt = (
            f"{user_prompt}\n\nThe quantitative workflow emitted the following event "
            f"stream. Interpret the results: {fixture['raw_events_truncated']}"
        )
    else:
        payload = json.dumps(fixture["workflow"], sort_keys=True, allow_nan=False)
        prompt = (
            f"{user_prompt}\n\nThe deterministic quantitative workflow completed. "
            f"Interpret these structured results without changing any value: {payload}"
        )
    if feedback:
        prompt += (
            "\n\nA reviewer found problems with your previous answer. "
            f"Rewrite it, fixing every issue:\n{feedback}"
        )
    return prompt


def _make_agent(model_id: str):
    from strands import Agent
    from strands.models import BedrockModel

    # No temperature/top_p/top_k: removed on Opus 5 (400 if sent).
    return Agent(
        model=BedrockModel(model_id=model_id),
        system_prompt=SYSTEM_PROMPT,
        tools=[],
        callback_handler=None,
    )


def _usage(result) -> tuple[int | None, int | None]:
    try:
        usage = result.metrics.accumulated_usage
        return usage["inputTokens"], usage["outputTokens"]
    except (AttributeError, KeyError, TypeError):
        return None, None


def generate(
    user_prompt: str,
    fixture: dict,
    feedback: str | None = None,
    model_id: str | None = None,
) -> Generation:
    agent = _make_agent(model_id or DEFAULT_MODEL_ID)
    started = time.monotonic()
    result = agent(build_prompt(user_prompt, fixture, feedback))
    latency = time.monotonic() - started
    input_tokens, output_tokens = _usage(result)
    return Generation(str(result), input_tokens, output_tokens, latency)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd experiments/reflexion && python -m pytest tests/test_smoke.py -v`
Expected: 4 PASS (no network — `strands` imports live inside `_make_agent`).

- [ ] **Step 5: One live sanity call (manual, ~$0.10)**

Run:
```bash
cd experiments/reflexion && python -c "
import json, generator
fx = json.load(open('fixtures/happy_path.json'))
g = generator.generate('Summarize this run in two sentences.', fx)
print(g.latency_s, g.input_tokens, g.output_tokens)
print(g.text[:400])
"
```
Expected: a coherent two-sentence summary citing fixture numbers. If Bedrock returns `AccessDeniedException` on `us.anthropic.claude-opus-5`, the model needs enabling in the Bedrock console — surface to user, don't silently switch models.

- [ ] **Step 6: Commit**

```bash
git add experiments/reflexion/generator.py experiments/reflexion/tests/test_smoke.py
git commit -m "feat(experiments): tool-less Strands generator replicating prod interpretation"
```

---

### Task 6: LLM critic (schema-forced semantic verdict)

**Files:**
- Create: `experiments/reflexion/critic.py`
- Modify: `experiments/reflexion/tests/test_smoke.py` (append)

**Interfaces:**
- Produces (used by Tasks 7, 8):
  - `CriticViolation(BaseModel)`: `type: Literal["numerical_overclaim","narrative_violation","missing_caveat","ungrounded_claim"]`, `claim: str`, `evidence: str`.
  - `CriticVerdict(BaseModel)`: `passed: bool`, `violations: list[CriticViolation]`.
  - `critique(narration: str, fixture: dict, model_id: str | None = None) -> CriticVerdict` (network).
  - `build_critic_prompt(narration: str, fixture: dict) -> str` (pure, testable).

- [ ] **Step 1: Append failing smoke tests**

Append to `experiments/reflexion/tests/test_smoke.py`:
```python
import critic  # noqa: E402


def test_critic_prompt_contains_narration_fixture_and_rubric():
    prompt = critic.build_critic_prompt("The PFE rose.", WORKFLOW_FIXTURE)
    assert "The PFE rose." in prompt
    assert '"execution_id": "e1"' in prompt
    assert "augments" in prompt  # narrative rubric present


def test_critic_verdict_schema():
    verdict = critic.CriticVerdict(passed=False, violations=[
        critic.CriticViolation(type="narrative_violation", claim="c", evidence="e"),
    ])
    assert verdict.violations[0].type == "narrative_violation"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd experiments/reflexion && python -m pytest tests/test_smoke.py -v`
Expected: new tests FAIL — `ModuleNotFoundError: No module named 'critic'`.

- [ ] **Step 3: Write `critic.py`**

```python
"""Layer-2 LLM critic: semantic faithfulness verdict (spec §2 items 1, 3, 4)."""
import json
import os
from typing import Literal

from pydantic import BaseModel

DEFAULT_MODEL_ID = os.environ.get("REFLEXION_MODEL_ID", "us.anthropic.claude-opus-5")

CRITIC_SYSTEM = """You are a quantitative-finance reviewer for a Numerix demo.
Judge whether a narration faithfully explains a Chronos-2 exposure run, using ONLY
the structured run artifacts provided. Deterministic checkers already verify exact
numbers, hashes, and IDs — do NOT re-verify arithmetic. You check semantics:

1. numerical_overclaim: directional or comparative claims the artifacts do not
   support (e.g. "Chronos-2 improved PFE" when augmented PFE is not better, or
   praising coverage the diagnostics do not show).
2. narrative_violation: the project story is "Chronos-2 AUGMENTS, never replaces,
   the parametric Monte Carlo engine". Flag any implication that Chronos-2 is the
   pricing engine, replaces the exposure machinery, or sees the same inputs as the
   baseline (only Chronos-2 sees the VIX/MOVE/WTI covariates — that asymmetry is
   deliberate).
3. missing_caveat: degraded/incomplete runs explained without caveats, or
   diagnostics limitations overstated (V1 diagnostics defend the headline only,
   not a full model-risk validation package).
4. ungrounded_claim: hand-waving that should cite coverage, tail dependence,
   w_stress, or provenance but cites nothing.

Pass the narration unless you find a concrete violation. Be specific: quote the
offending claim and the artifact evidence."""


class CriticViolation(BaseModel):
    type: Literal[
        "numerical_overclaim", "narrative_violation", "missing_caveat", "ungrounded_claim"
    ]
    claim: str
    evidence: str


class CriticVerdict(BaseModel):
    passed: bool
    violations: list[CriticViolation]


def build_critic_prompt(narration: str, fixture: dict) -> str:
    artifacts = json.dumps(
        fixture.get("workflow", {"raw_events_truncated": fixture.get("raw_events_truncated")}),
        sort_keys=True, allow_nan=False,
    )
    return (
        f"Run artifacts (ground truth):\n{artifacts}\n\n"
        f"Run posture: {fixture.get('expected_posture')}, defect: {fixture.get('defect')}.\n"
        "Remember: Chronos-2 augments, never replaces, the Monte Carlo engine.\n\n"
        f"Narration under review:\n---\n{narration}\n---\n\n"
        "Return your verdict."
    )


def critique(narration: str, fixture: dict, model_id: str | None = None) -> CriticVerdict:
    from strands import Agent
    from strands.models import BedrockModel

    agent = Agent(
        model=BedrockModel(model_id=model_id or DEFAULT_MODEL_ID),
        system_prompt=CRITIC_SYSTEM,
        tools=[],
        callback_handler=None,
    )
    return agent.structured_output(CriticVerdict, build_critic_prompt(narration, fixture))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd experiments/reflexion && python -m pytest tests/test_smoke.py -v`
Expected: 6 PASS.

- [ ] **Step 5: One live sanity call (manual)**

```bash
cd experiments/reflexion && python -c "
import json, critic
fx = json.load(open('fixtures/happy_path.json'))
v = critic.critique('Chronos-2 replaced the Monte Carlo engine and now prices the book directly.', fx)
print(v.passed, [x.type for x in v.violations])
"
```
Expected: `passed=False` with at least one `narrative_violation`.

- [ ] **Step 6: Commit**

```bash
git add experiments/reflexion/critic.py experiments/reflexion/tests/test_smoke.py
git commit -m "feat(experiments): schema-forced LLM critic for semantic faithfulness"
```

---

### Task 7: Reflexion loop (pure orchestration)

**Files:**
- Create: `experiments/reflexion/loop.py`, `experiments/reflexion/tests/test_loop.py`

**Interfaces:**
- Consumes: callables with the shapes of Task 5/6 outputs (injected, so tests are hermetic).
- Produces (used by Task 8):
  - `Attempt` dataclass: `narration: str`, `oracle_violations: list[dict]`, `critic_verdict` (CriticVerdict-shaped, `.passed` / `.violations`), `latency_s: float`, `input_tokens: int | None`, `output_tokens: int | None`.
  - `LoopResult` dataclass: `final: str`, `iterations: int`, `converged: bool`, `attempts: list[Attempt]`.
  - `run_reflexion(generate_fn, validate_fn, critique_fn, max_iters: int = 3) -> LoopResult` where `generate_fn(feedback: str | None) -> Generation-shaped`, `validate_fn(narration) -> list[dict]`, `critique_fn(narration) -> CriticVerdict-shaped`.
  - `format_feedback(oracle_violations, critic_verdict) -> str`.

- [ ] **Step 1: Write the failing tests**

`experiments/reflexion/tests/test_loop.py`:
```python
import pathlib
import sys
from dataclasses import dataclass

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import loop  # noqa: E402


@dataclass
class FakeGen:
    text: str
    input_tokens: int = 10
    output_tokens: int = 20
    latency_s: float = 0.1


@dataclass
class FakeVerdict:
    passed: bool
    violations: list


def test_converges_first_pass_when_clean():
    result = loop.run_reflexion(
        generate_fn=lambda feedback: FakeGen("good"),
        validate_fn=lambda text: [],
        critique_fn=lambda text: FakeVerdict(True, []),
    )
    assert result.converged and result.iterations == 1 and result.final == "good"


def test_feedback_carries_both_layers_and_loop_retries():
    calls = []

    def generate_fn(feedback):
        calls.append(feedback)
        return FakeGen("bad" if len(calls) == 1 else "good")

    result = loop.run_reflexion(
        generate_fn=generate_fn,
        validate_fn=lambda text: (
            [{"type": "invented_value", "detail": "999 not in artifacts"}] if text == "bad" else []
        ),
        critique_fn=lambda text: (
            FakeVerdict(False, [FakeVerdict(False, [])]) if text == "bad" else FakeVerdict(True, [])
        ),
    )
    assert result.converged and result.iterations == 2
    assert calls[0] is None
    assert "invented_value" in calls[1] and "999 not in artifacts" in calls[1]


def test_gives_up_after_max_iters():
    result = loop.run_reflexion(
        generate_fn=lambda feedback: FakeGen("always bad"),
        validate_fn=lambda text: [{"type": "wrong_value", "detail": "x"}],
        critique_fn=lambda text: FakeVerdict(True, []),
        max_iters=3,
    )
    assert not result.converged and result.iterations == 3
    assert len(result.attempts) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd experiments/reflexion && python -m pytest tests/test_loop.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'loop'`.

- [ ] **Step 3: Write `loop.py`**

```python
"""Reflexion loop: generate -> oracle -> critic -> regenerate with feedback (spec §3)."""
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Attempt:
    narration: str
    oracle_violations: list
    critic_verdict: Any
    latency_s: float
    input_tokens: int | None
    output_tokens: int | None


@dataclass
class LoopResult:
    final: str
    iterations: int
    converged: bool
    attempts: list = field(default_factory=list)


def format_feedback(oracle_violations: list, critic_verdict: Any) -> str:
    lines = [
        f"- [{violation['type']}] {violation['detail']}" for violation in oracle_violations
    ]
    if not getattr(critic_verdict, "passed", True):
        for violation in getattr(critic_verdict, "violations", []):
            claim = getattr(violation, "claim", "")
            evidence = getattr(violation, "evidence", "")
            vtype = getattr(violation, "type", "critic_finding")
            lines.append(f"- [{vtype}] {claim} (evidence: {evidence})")
    return "\n".join(lines)


def run_reflexion(
    generate_fn: Callable[[str | None], Any],
    validate_fn: Callable[[str], list],
    critique_fn: Callable[[str], Any],
    max_iters: int = 3,
) -> LoopResult:
    feedback = None
    attempts: list[Attempt] = []
    for iteration in range(1, max_iters + 1):
        generation = generate_fn(feedback)
        narration = generation.text
        oracle_violations = validate_fn(narration)
        verdict = critique_fn(narration)
        attempts.append(Attempt(
            narration, oracle_violations, verdict,
            generation.latency_s, generation.input_tokens, generation.output_tokens,
        ))
        if not oracle_violations and getattr(verdict, "passed", False):
            return LoopResult(narration, iteration, True, attempts)
        feedback = format_feedback(oracle_violations, verdict)
    return LoopResult(narration, max_iters, False, attempts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd experiments/reflexion && python -m pytest tests/test_loop.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add experiments/reflexion/loop.py experiments/reflexion/tests/test_loop.py
git commit -m "feat(experiments): reflexion loop with two-layer feedback"
```

---

### Task 8: Scenario matrix + experiment harness + README

**Files:**
- Create: `experiments/reflexion/scenarios.py`, `experiments/reflexion/run_experiment.py`, `experiments/reflexion/README.md`
- Modify: `experiments/reflexion/tests/test_smoke.py` (append)

**Interfaces:**
- Consumes: `generator.generate`/`Generation`, `critic.critique`, `validator.validate`, `loop.run_reflexion`.
- Produces: `scenarios.SCENARIOS: list[dict]` with keys `name`, `fixture_file`, `prompt`; `run_experiment.main()` CLI (`--trials`, `--arms`, `--scenarios`, `--max-iters`); results JSON at `results/experiment_<timestamp>.json`.

- [ ] **Step 1: Write `scenarios.py`** (spec §6 mapping, verbatim)

```python
"""Scenario -> fixture/prompt matrix (spec §6)."""
STANDARD_PROMPT = (
    "Explain this exposure run: compare baseline and Chronos-2-augmented PFE, "
    "describe the market regime, and note anything unusual."
)

SCENARIOS = [
    {"name": "happy_path", "fixture_file": "happy_path.json", "prompt": STANDARD_PROMPT},
    {"name": "conditional_whatif", "fixture_file": "conditional_whatif.json",
     "prompt": STANDARD_PROMPT},
    {"name": "ambiguous", "fixture_file": "happy_path.json", "prompt": "so how did it go?"},
    {"name": "failed_tool_missing", "fixture_file": "missing_exposure.json",
     "prompt": STANDARD_PROMPT},
    {"name": "failed_tool_id_mismatch", "fixture_file": "id_mismatch.json",
     "prompt": STANDARD_PROMPT},
    {"name": "failed_tool_partial", "fixture_file": "partial_events.json",
     "prompt": STANDARD_PROMPT},
    {"name": "misleading", "fixture_file": "happy_path.json",
     "prompt": ("Explain how Chronos-2 replaced the Monte Carlo engine and how much "
                "it improved the PFE.")},
]
```

- [ ] **Step 2: Append a hermetic smoke test for the harness plumbing**

Append to `experiments/reflexion/tests/test_smoke.py`:
```python
import scenarios  # noqa: E402
import run_experiment  # noqa: E402


def test_scenarios_reference_existing_fixtures():
    fixture_dir = pathlib.Path(__file__).resolve().parents[1] / "fixtures"
    for scenario in scenarios.SCENARIOS:
        assert (fixture_dir / scenario["fixture_file"]).exists(), scenario["name"]


def test_summarize_computes_rates_and_critic_prf():
    trials = [
        {"arm": "A", "scenario": "s", "oracle_violations": [{"type": "invented_value"}],
         "critic_passed": False, "iterations": 1, "latency_s": 1.0,
         "input_tokens": 10, "output_tokens": 5, "converged": True},
        {"arm": "A", "scenario": "s", "oracle_violations": [],
         "critic_passed": True, "iterations": 1, "latency_s": 1.0,
         "input_tokens": 10, "output_tokens": 5, "converged": True},
    ]
    summary = run_experiment.summarize(trials)
    arm = summary["A"]
    assert arm["trials"] == 2
    assert arm["oracle_violation_rate"] == 0.5
    assert arm["critic_precision"] == 1.0 and arm["critic_recall"] == 1.0
```

Run: `cd experiments/reflexion && python -m pytest tests/test_smoke.py -v`
Expected: new tests FAIL — `No module named 'run_experiment'` (scenarios.py exists from Step 1).

- [ ] **Step 3: Write `run_experiment.py`**

```python
"""Experiment harness: arms x scenarios x trials, oracle-scored (spec §6)."""
import argparse
import json
import pathlib
import time
from collections import defaultdict

import critic as critic_mod
import generator
import scenarios as scenarios_mod
import validator
from loop import run_reflexion

HERE = pathlib.Path(__file__).resolve().parent


def _load_fixture(name: str) -> dict:
    with open(HERE / "fixtures" / name, encoding="utf-8") as fh:
        return json.load(fh)


def run_trial(arm: str, scenario: dict, max_iters: int) -> dict:
    fixture = _load_fixture(scenario["fixture_file"])
    if arm == "A":
        generation = generator.generate(scenario["prompt"], fixture)
        narration = generation.text
        iterations, converged = 1, True
        latency = generation.latency_s
        input_tokens, output_tokens = generation.input_tokens, generation.output_tokens
        critic_passed = None  # Arm A never consults the critic
    else:
        result = run_reflexion(
            generate_fn=lambda fb: generator.generate(scenario["prompt"], fixture, feedback=fb),
            validate_fn=lambda text: validator.validate(text, fixture),
            critique_fn=lambda text: critic_mod.critique(text, fixture),
            max_iters=max_iters,
        )
        narration = result.final
        iterations, converged = result.iterations, result.converged
        latency = sum(a.latency_s for a in result.attempts)
        input_tokens = sum(a.input_tokens or 0 for a in result.attempts)
        output_tokens = sum(a.output_tokens or 0 for a in result.attempts)
        critic_passed = result.attempts[-1].critic_verdict.passed
    # Impartial final score: every narration in BOTH arms gets oracle-scored,
    # plus (for critic P/R) a fresh critic verdict on Arm A finals.
    oracle_violations = validator.validate(narration, fixture)
    if critic_passed is None:
        critic_passed = critic_mod.critique(narration, fixture).passed
    return {
        "arm": arm, "scenario": scenario["name"], "narration": narration,
        "oracle_violations": oracle_violations, "critic_passed": critic_passed,
        "iterations": iterations, "converged": converged, "latency_s": latency,
        "input_tokens": input_tokens, "output_tokens": output_tokens,
    }


def summarize(trials: list[dict]) -> dict:
    summary = {}
    by_arm = defaultdict(list)
    for trial in trials:
        by_arm[trial["arm"]].append(trial)
    for arm, rows in sorted(by_arm.items()):
        total = len(rows)
        flagged_oracle = [bool(r["oracle_violations"]) for r in rows]
        flagged_critic = [not r["critic_passed"] for r in rows]
        true_pos = sum(c and o for c, o in zip(flagged_critic, flagged_oracle))
        critic_flags = sum(flagged_critic)
        oracle_flags = sum(flagged_oracle)
        summary[arm] = {
            "trials": total,
            "oracle_violation_rate": oracle_flags / total,
            "violation_types": _type_counts(rows),
            "critic_precision": true_pos / critic_flags if critic_flags else None,
            "critic_recall": true_pos / oracle_flags if oracle_flags else None,
            "mean_iterations": sum(r["iterations"] for r in rows) / total,
            "mean_latency_s": sum(r["latency_s"] for r in rows) / total,
            "total_tokens": sum((r["input_tokens"] or 0) + (r["output_tokens"] or 0)
                                for r in rows),
        }
    return summary


def _type_counts(rows: list[dict]) -> dict:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        for violation in row["oracle_violations"]:
            counts[violation["type"]] += 1
    return dict(counts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--arms", default="A,B")
    parser.add_argument("--scenarios", default="")  # comma list; empty = all
    parser.add_argument("--max-iters", type=int, default=3)
    args = parser.parse_args()
    wanted = set(filter(None, args.scenarios.split(",")))
    matrix = [s for s in scenarios_mod.SCENARIOS if not wanted or s["name"] in wanted]
    trials = []
    for scenario in matrix:
        for arm in args.arms.split(","):
            for trial_index in range(args.trials):
                print(f"[{scenario['name']}] arm={arm} trial={trial_index + 1}/{args.trials}")
                try:
                    trials.append(run_trial(arm, scenario, args.max_iters))
                except Exception as exc:  # record and continue; experiment, not prod
                    trials.append({"arm": arm, "scenario": scenario["name"],
                                   "error": f"{type(exc).__name__}: {exc}",
                                   "oracle_violations": [], "critic_passed": True,
                                   "iterations": 0, "converged": False,
                                   "latency_s": 0.0, "input_tokens": 0, "output_tokens": 0})
                    print(f"  FAILED: {exc}")
    ok_trials = [t for t in trials if "error" not in t]
    output = {"summary": summarize(ok_trials), "failed_trials":
              [t for t in trials if "error" in t], "trials": trials}
    out_path = HERE / "results" / f"experiment_{int(time.time())}.json"
    out_path.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
    print(json.dumps(output["summary"], indent=2))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run all experiment tests**

Run: `cd experiments/reflexion && python -m pytest tests/ -v`
Expected: all PASS (test_mutate 3, test_validator 10, test_loop 3, test_smoke 8). Then run root `pytest` from repo root — expected: unchanged pass count, experiments not collected.

- [ ] **Step 5: Write `README.md`**

```markdown
# Reflexion Critic Experiment

Local-only playground (spec: `docs/superpowers/specs/2026-08-13-reflexion-critic-experiment-design.md`).
Measures whether a deterministic-validator + LLM-critic reflexion loop improves
faithfulness of agent narration to structured run artifacts. Never deployed.

## Setup
    source ../../.venv/bin/activate
    pip install -r requirements.txt          # strands-agents
    export AWS_PROFILE=<profile>             # Bedrock access, us-east-1

## Run
    python run_experiment.py --trials 5                       # full matrix (~$10-30)
    python run_experiment.py --trials 2 --scenarios happy_path  # cheap smoke

## Reading results (results/experiment_<ts>.json)
- `summary.A` vs `summary.B`: Arm A = single pass (no critic), Arm B = reflexion loop.
- `oracle_violation_rate`: headline — did reflexion reduce unfaithful narrations?
- `violation_types`: wrong_value / invented_value / wrong_identifier /
  overconfident_degraded / missing_acknowledgement.
- `critic_precision` / `critic_recall`: LLM critic judged against the deterministic
  oracle on the mechanically checkable subset (narration-level flags). Semantic-only
  findings (narrative violations, caveats) have no oracle — inspect `trials[*].narration`.
- Cost side: `mean_iterations`, `mean_latency_s`, `total_tokens`.

## Caveats
- Opus 5 rejects temperature; trial variance is natural sampling only.
- Arm A is not "production" (prod interprets with Sonnet 4.6):
  rerun with `REFLEXION_MODEL_ID=us.anthropic.claude-sonnet-4-6` to compare.
- Regex claim extraction misses oddly-phrased numbers; check transcripts.
```

- [ ] **Step 6: Commit**

```bash
git add experiments/reflexion
git commit -m "feat(experiments): scenario matrix, experiment harness, README"
```

---

### Task 9: Run the experiment (live)

**Files:**
- Create: `experiments/reflexion/results/experiment_<timestamp>.json` (gitignored; do NOT commit)

- [ ] **Step 1: Cheap smoke run**

Run: `cd experiments/reflexion && python run_experiment.py --trials 1 --scenarios happy_path,failed_tool_missing`
Expected: 4 trials (2 scenarios × 2 arms), summary prints, results file written. Watch for: Arm B iterating on the degraded fixture (generator should acknowledge the missing result by iteration ≤3).

- [ ] **Step 2: Full run**

Run: `cd experiments/reflexion && python run_experiment.py --trials 5`
Expected: 70 trials (7 scenarios × 2 arms × 5), ~30–60 min wall-clock, low tens of dollars. `summary.B.oracle_violation_rate ≤ summary.A.oracle_violation_rate` is the hypothesis — report whatever the data says, including a null result.

- [ ] **Step 3: Report findings to the user**

Summarize: violation rates per arm (overall and per scenario from `trials`), critic precision/recall, iteration/token/latency costs, and 2–3 illustrative transcripts (one caught fabrication, one narrative violation, one degraded-run acknowledgement). No commit — results stay local.

---

## Self-Review Notes

- Spec §1–§6 coverage: fixtures+capture (T1), mutations (T2), oracle numeric (T3), oracle structural/posture (T4), generator (T5), critic (T6), loop (T7), matrix+harness+scoring+README (T8), live run (T9). Spec §7 (hermetic tests, loud failures) enforced per-task; §8 out-of-scope respected (no prod files touched).
- Scenario count: spec says 5 scenario classes; the harness expands "failed tool" into its 3 fixtures → 7 matrix rows. Intentional.
- Critic P/R vs oracle uses narration-level flags (did-flag vs should-flag); documented in README.
- Type consistency: `Generation(text, input_tokens, output_tokens, latency_s)` (T5) matches loop usage (T7) and harness (T8); `validate(narration, fixture) -> list[dict]` used identically in T7/T8; `CriticVerdict.passed/.violations` consistent T6/T7/T8.
```
