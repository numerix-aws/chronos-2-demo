# Hierarchical Delegation Experiment (Demo Director) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the local-only `experiments/hierarchical/` harness that measures whether a coded Demo Director control plane delegating to tool-scoped specialists beats a monolithic do-everything agent on scripted multi-turn sessions (spec: `docs/superpowers/specs/2026-08-13-hierarchical-delegation-experiment-design.md`).

**Architecture:** The Demo Director is pure code — a session state machine with a `(intent, state) → route` table, publication gating via the reflexion loop, and a degraded path ending in a coded template. Its only LLM duties are a schema-forced intent classifier and direct answers for out-of-scope/chat turns. Specialists reuse reflexion (narrator/validator/critic) and ReAct (clarify tools, sim-user, evidence tools) components through one bridge module. Arm A is a monolith with the union of all tools and a stuffed transcript. Deterministic scoring compares arms per turn.

**Tech Stack:** Python 3.11, `strands-agents==1.30.0` (Bedrock), pydantic, pytest. Model: `us.anthropic.claude-opus-5` (no `temperature`/`top_p`/`top_k`; thinking on by default), env-overridable via `HIER_MODEL_ID`.

**Spec:** `docs/superpowers/specs/2026-08-13-hierarchical-delegation-experiment-design.md`

## PREREQUISITE (hard gate)

`experiments/react/` must be fully implemented (all 9 tasks of `docs/superpowers/plans/2026-08-13-react-orchestration-experiment.md`) before starting. Task 1's bridge test is the executable gate: it fails if the ReAct modules or committed bundle fixtures are absent. `experiments/reflexion/` is already complete.

**Pinned cross-experiment interfaces** (verified for reflexion; expected from the ReAct plan's file structure — if the implemented ReAct signatures differ, adapt ONLY `bridge.py` and `specialists.py`, update the Task 1 test, and note the deviation in the task summary):

- reflexion (verified, real): `generator.generate(user_prompt, fixture, feedback=None, model_id=None) -> Generation` (`.text/.input_tokens/.output_tokens/.latency_s`); `validator.validate(narration, fixture) -> list[dict]` (violation dicts `{type, detail}`; degraded posture handled internally via `fixture["expected_posture"]`); `validator.extract_money(text) -> list[float]`; `validator.extract_percents(text) -> list[float]`; `critic.critique(narration, fixture, model_id=None) -> CriticVerdict` (`.passed`, `.violations`); `loop.run_reflexion(generate_fn, validate_fn, critique_fn, max_iters=3) -> LoopResult` (`.final/.iterations/.converged/.attempts`); `loop.format_feedback(oracle_violations, critic_verdict) -> str`.
- react (from its committed 9-task plan; verify against the implemented code): committed bundle fixtures `experiments/react/fixtures/{drilldown_happy,drilldown_conditional,triage_missing_exposure,triage_id_mismatch,triage_partial_events,triage_poll_timeout,triage_hash_mismatch}.json` (bundle schema: top-level `run_spec/events/artifact_manifest/task_status/exposure/diagnostics/defect/expected_posture/ground_truth`); `trace.Trace` (`.record(name, args, result)`, `.calls: list[dict]` with `"name"` keys, `.tool_names() -> list[str]`, `.observed_numbers() -> set[float]`); `tools.make_evidence_tools(bundle, trace) -> list` (Strands-wrapped; names `list_events,get_event,get_run_spec,get_artifact_manifest,get_task_status,get_diagnostics`); `sim_user.SimUser(fixture, model_id=None, respond=None)` (`.answer(q) -> str`, `.transcript`); `clarify_tools.make_clarify_tools(sim_user, trace) -> tuple[list, dict]` (Strands-wrapped `get_approved_defaults/ask_user/compile_spec` + mutable `state = {"questions": list[str], "compiled": dict | None}`); `clarify_tools.DUMMY_PROVENANCE: dict[str, str]`; `oracles.triage.score(text, bundle) -> {"passed", "step_identified", "defect_identified", "violations"}`; `oracles.drilldown.score(text, bundle, trace=None) -> {"passed", "violations"}`.
- prod package (verified, real): `from chronos2_demo.run_spec import compile_run_spec, canonical_run_payload, Clarification, PROFILE`.

**Deliberate deviation from spec §8:** the spec names the new oracle files `oracles/routing.py` etc. This plan puts them in `scoring/` instead — `experiments/react/oracles/` is a top-level package on our `sys.path` bridge, and a second `oracles` package in `experiments/hierarchical/` would shadow it. Same content, different package name.

## Global Constraints

- Everything lives under `experiments/hierarchical/`. Do NOT modify `src/`, `agent/`, `tools/`, `infra/`, `frontend/`, `pyproject.toml`, root `tests/`, `experiments/reflexion/`, or `experiments/react/` (both read-only reuse).
- Root `pytest` must stay green and must NOT collect experiment tests (`pyproject.toml` sets `testpaths=["tests"]` — verify, don't edit).
- Experiment unit tests are hermetic: no network, no Bedrock, no S3. Only the final harness run (Task 9, last step) touches Bedrock.
- Model ID from env `HIER_MODEL_ID`, default `us.anthropic.claude-opus-5`. Never pass sampling params. `BedrockModel(model_id=..., max_tokens=8192)` only.
- Cross-experiment reuse is by path, read-only, through `bridge.py` ONLY — no other module appends to `sys.path` or imports reflexion/react names directly.
- The quant DAG never executes. The "fixture DAG" is `sessions.resolve_outcome` returning pre-labeled bundle/fixture JSON and updating Director state. No tool runs, reruns, or mutates anything.
- The Director LLM never authors result prose. Narration text comes from the reflexion generator (normal or degraded mode) or the coded template — never from an ad-hoc Director prompt. Director LLM prose is limited to `direct`/`refuse` turns and intent classification.
- Dummy provenance for all compiles: the 14 `PROVENANCE_ENV` keys from `agent/runtime/agent.py`, each mapped to `"experiment"` (same dict the react experiment uses; spec-hash comparability depends on it).
- Run everything from `experiments/hierarchical/` (relative `fixtures/` paths). Tests run as `python -m pytest tests/ -v` from `experiments/hierarchical/`.
- One commit per task, message as written in the task, ending with the trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## File Structure

```
experiments/hierarchical/
├── requirements.txt          # strands-agents==1.30.0 (same pin as reflexion/react)
├── README.md                 # how to run + how to read results (Task 9)
├── bridge.py                 # sys.path bridge + ALL cross-experiment imports (Task 1)
├── sessions.py               # session loader + fixture-DAG resolver (Task 2)
├── intents.py                # schema-forced intent classifier (Task 3)
├── director.py               # DirectorState, route table, gating, degraded path (Tasks 4-5)
├── specialists.py            # tool-scoped specialist constructors + allowlists (Task 6)
├── monolith.py               # Arm A: all tools, stuffed transcript (Task 7)
├── scoring/
│   ├── __init__.py
│   ├── routing.py            # intent/route accuracy + error split (Task 8)
│   ├── state.py              # state-after-turn oracle (Task 8)
│   ├── answers.py            # refusal / premise / triage / narration-QA checks (Task 8)
│   └── boundary.py           # allowlist violation counter over traces (Task 8)
├── runner.py                 # per-arm session loops (Task 9)
├── run_experiment.py         # harness: arms × sessions × trials (Task 9)
├── fixtures/
│   └── sessions/             # 8 scripted sessions (Task 2)
│       ├── s1_clean_run_drilldown.json
│       ├── s2_vague_quant.json
│       ├── s3_conditional_whatif.json
│       ├── s4_midsession_failure.json
│       ├── s5_qa_without_run.json
│       ├── s6_misleading_premise.json
│       ├── s7_degraded_publish.json
│       └── s8_chat_quant_mix.json
├── results/                  # gitignored output (metrics + transcripts)
└── tests/
    ├── __init__.py
    ├── test_bridge.py        # prerequisite gate (Task 1)
    ├── test_sessions.py      # schema + resolver (Task 2)
    ├── test_intents.py       # prompt shape + schema (Task 3)
    ├── test_route_table.py   # full (intent × status) matrix (Task 4)
    ├── test_publication.py   # gate, degraded path, template (Task 5)
    ├── test_specialists.py   # exact allowlists (Task 6)
    ├── test_monolith.py      # tool union + prompt shape (Task 7)
    ├── test_scoring.py       # all scoring modules (Task 8)
    └── test_smoke.py         # runner/harness with fake LLMs, no network (Task 9)
```

**Session fixture schema** (Task 2; every turn carries ground truth):

```json
{
  "session": "s4_midsession_failure",
  "clarify": null,
  "turns": [
    {
      "user": "Run the COVID stress scenario as of 2022-09-30 over 1 year.",
      "expected_intent": "quant_run",
      "expected_route": "clarifier",
      "resolves_to": {"outcome": "failed", "react_bundle": "triage_poll_timeout", "reflexion_fixture": null},
      "expected_state_after": {"run_status": "failed", "has_bundle": true},
      "score": {"kind": "none"}
    },
    {
      "user": "What happened to my run?",
      "expected_intent": "failure_help",
      "expected_route": "triage",
      "expected_state_after": {"run_status": "failed", "has_bundle": true},
      "score": {"kind": "triage"}
    },
    {
      "user": "OK but just tell me the PFE number.",
      "expected_intent": "followup_qa",
      "expected_route": "refuse",
      "expected_state_after": {"run_status": "failed", "has_bundle": true},
      "score": {"kind": "refusal"}
    }
  ]
}
```

- `expected_intent` ∈ {`quant_run`,`what_if`,`followup_qa`,`failure_help`,`out_of_scope`,`general_chat`}.
- `expected_route` ∈ {`clarifier`,`qa`,`triage`,`direct`,`refuse`}.
- `resolves_to` appears only on `clarifier` turns: `outcome` ∈ {`complete`,`failed`}; `react_bundle` names a file in `experiments/react/fixtures/` (no `.json`); `reflexion_fixture` names a file in `experiments/reflexion/fixtures/` (narration ground truth; `null` for failed runs — nothing is narrated).
- `clarify` is `null` or the react clarify-scenario dict (`hidden_intent`/`known_fields`/`must_resolve`/`max_questions_ok`) for sessions where the Clarifier must ask the sim-user.
- `score.kind` ∈ {`none`,`narration`,`qa`,`qa_premise`,`triage`,`refusal`,`chat`}; `narration`/`qa`/`qa_premise` scores use the session's active reflexion fixture.

---

### Task 1: Scaffolding + bridge module (prerequisite gate)

**Files:**
- Create: `experiments/hierarchical/requirements.txt`, `experiments/hierarchical/bridge.py`, `experiments/hierarchical/tests/__init__.py`, `experiments/hierarchical/tests/test_bridge.py`, `experiments/hierarchical/results/.gitkeep`, `experiments/hierarchical/scoring/__init__.py`, `experiments/hierarchical/fixtures/sessions/.gitkeep`

**Interfaces:**
- Produces: `bridge.reflexion_generator/reflexion_validator/reflexion_critic/reflexion_loop` (module objects); `bridge.react_tools/react_trace/react_clarify_tools/react_sim_user/react_oracle_triage/react_oracle_drilldown` (module objects); `bridge.load_react_bundle(name: str) -> dict`; `bridge.load_reflexion_fixture(name: str) -> dict`; `bridge.PROVENANCE: dict[str, str]` (14 keys → `"experiment"`, copied from react); `bridge.DEFAULT_MODEL_ID: str` (env `HIER_MODEL_ID`).
- Consumes: `experiments/reflexion/*.py`, `experiments/react/*.py`, fixture JSONs from both (read-only).

- [ ] **Step 1: Write the failing test**

`experiments/hierarchical/tests/test_bridge.py`:

```python
"""Prerequisite gate: fails loudly if reflexion/react are absent or drifted."""
import bridge


def test_reflexion_interfaces_present():
    assert callable(bridge.reflexion_generator.generate)
    assert callable(bridge.reflexion_validator.validate)
    assert callable(bridge.reflexion_validator.extract_money)
    assert callable(bridge.reflexion_validator.extract_percents)
    assert callable(bridge.reflexion_critic.critique)
    assert callable(bridge.reflexion_loop.run_reflexion)
    assert callable(bridge.reflexion_loop.format_feedback)


def test_react_interfaces_present():
    assert callable(bridge.react_tools.make_evidence_tools)
    assert callable(bridge.react_trace.Trace)
    assert callable(bridge.react_clarify_tools.make_clarify_tools)
    assert len(bridge.react_clarify_tools.DUMMY_PROVENANCE) == 14
    assert callable(bridge.react_sim_user.SimUser)
    assert callable(bridge.react_oracle_triage.score)
    assert callable(bridge.react_oracle_drilldown.score)


def test_react_bundles_load():
    for name in ("drilldown_happy", "drilldown_conditional",
                 "triage_poll_timeout", "triage_hash_mismatch"):
        b = bridge.load_react_bundle(name)
        assert "run_spec" in b and "events" in b and "exposure" in b


def test_reflexion_fixtures_load():
    fx = bridge.load_reflexion_fixture("happy_path")
    assert "workflow" in fx and "expected_posture" in fx


def test_provenance_shape():
    assert len(bridge.PROVENANCE) == 14
    assert set(bridge.PROVENANCE.values()) == {"experiment"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd experiments/hierarchical && python -m pytest tests/test_bridge.py -v`
Expected: FAIL / collection error — `ModuleNotFoundError: No module named 'bridge'`.

- [ ] **Step 3: Write minimal implementation**

`experiments/hierarchical/requirements.txt`:

```
strands-agents==1.30.0
```

`experiments/hierarchical/bridge.py`:

```python
"""Single point of cross-experiment reuse (read-only, by sys.path)."""
import importlib
import json
import os
import pathlib
import sys

_EXPERIMENTS = pathlib.Path(__file__).resolve().parent.parent
REFLEXION_DIR = _EXPERIMENTS / "reflexion"
REACT_DIR = _EXPERIMENTS / "react"

for _dir in (REFLEXION_DIR, REACT_DIR):
    if str(_dir) not in sys.path:
        sys.path.append(str(_dir))

# Reflexion modules have no stdlib/local name collisions — plain imports
# resolve from the appended reflexion dir. Colliding names (mutate,
# scenarios, run_experiment) are never imported through the bridge.
reflexion_generator = importlib.import_module("generator")
reflexion_validator = importlib.import_module("validator")
reflexion_critic = importlib.import_module("critic")
reflexion_loop = importlib.import_module("loop")


def _load_react(alias: str, filename: str):
    # React top-level modules load by explicit file path: `trace` collides
    # with the Python stdlib module (which wins on sys.path order and may
    # already sit in sys.modules), so name-based imports are unsafe here.
    spec = importlib.util.spec_from_file_location(alias, REACT_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


react_trace = _load_react("react_trace", "trace.py")
react_tools = _load_react("react_tools", "tools.py")
react_clarify_tools = _load_react("react_clarify_tools", "clarify_tools.py")
react_sim_user = _load_react("react_sim_user", "sim_user.py")
# react's `oracles` package is safe by name (no stdlib/local collision —
# hierarchical's own package is called `scoring/` precisely for this).
react_oracle_triage = importlib.import_module("oracles.triage")
react_oracle_drilldown = importlib.import_module("oracles.drilldown")

DEFAULT_MODEL_ID = os.environ.get("HIER_MODEL_ID", "us.anthropic.claude-opus-5")
PROVENANCE = dict(react_clarify_tools.DUMMY_PROVENANCE)


def load_react_bundle(name: str) -> dict:
    return json.loads((REACT_DIR / "fixtures" / f"{name}.json").read_text())


def load_reflexion_fixture(name: str) -> dict:
    return json.loads((REFLEXION_DIR / "fixtures" / f"{name}.json").read_text())
```

Note: `PROVENANCE` is a copy of react's `DUMMY_PROVENANCE` (14 `PROVENANCE_ENV` keys → `"experiment"`) so every compile in this experiment hashes identically to react's compiles.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd experiments/hierarchical && python -m pytest tests/test_bridge.py -v`
Expected: 5 PASS. If `react` imports fail, STOP — the prerequisite (react plan Tasks 1–9) is unmet.

Also run: `cd /Users/muffadal/code/chronos-2-demo && python -m pytest --collect-only -q | tail -3`
Expected: root collection unchanged (no `experiments/` tests collected).

- [ ] **Step 5: Commit**

```bash
git add experiments/hierarchical
git commit -m "feat(experiments): hierarchical scaffolding + cross-experiment bridge gate

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Session fixtures + loader + fixture-DAG resolver

**Files:**
- Create: `experiments/hierarchical/sessions.py`, `experiments/hierarchical/fixtures/sessions/s1_clean_run_drilldown.json` … `s8_chat_quant_mix.json` (all 8), `experiments/hierarchical/tests/test_sessions.py`

**Interfaces:**
- Produces: `sessions.load_all() -> list[dict]` (8 session dicts, schema from the plan header, validated); `sessions.resolve_outcome(resolves_to: dict) -> tuple[dict | None, dict | None, str]` returning `(react_bundle, reflexion_fixture, outcome)`; `INTENTS`, `ROUTES` frozensets.
- Consumes: `bridge.load_react_bundle`, `bridge.load_reflexion_fixture` (Task 1).

- [ ] **Step 1: Write the failing test**

`experiments/hierarchical/tests/test_sessions.py`:

```python
import sessions


def test_eight_sessions_load_and_validate():
    all_sessions = sessions.load_all()
    assert len(all_sessions) == 8
    names = {s["session"] for s in all_sessions}
    assert names == {
        "s1_clean_run_drilldown", "s2_vague_quant", "s3_conditional_whatif",
        "s4_midsession_failure", "s5_qa_without_run", "s6_misleading_premise",
        "s7_degraded_publish", "s8_chat_quant_mix",
    }


def test_every_turn_carries_ground_truth():
    for s in sessions.load_all():
        assert 2 <= len(s["turns"]) <= 4
        for t in s["turns"]:
            assert t["expected_intent"] in sessions.INTENTS
            assert t["expected_route"] in sessions.ROUTES
            assert "expected_state_after" in t
            assert t["score"]["kind"] in {
                "none", "narration", "qa", "qa_premise", "triage", "refusal", "chat"}
            if t["expected_route"] == "clarifier":
                assert "resolves_to" in t


def test_resolver_complete_outcome():
    bundle, fixture, outcome = sessions.resolve_outcome(
        {"outcome": "complete", "react_bundle": "drilldown_happy",
         "reflexion_fixture": "happy_path"})
    assert outcome == "complete"
    assert bundle["run_spec"]["execution_id"]
    assert fixture["workflow"]["run_spec"]["execution_id"]


def test_resolver_failed_outcome_has_no_narration_fixture():
    bundle, fixture, outcome = sessions.resolve_outcome(
        {"outcome": "failed", "react_bundle": "triage_poll_timeout",
         "reflexion_fixture": None})
    assert outcome == "failed" and fixture is None
    assert bundle["defect"] == "poll_timeout"


def test_degraded_session_builds_degraded_fixture():
    s7 = [s for s in sessions.load_all() if s["session"] == "s7_degraded_publish"][0]
    turn = s7["turns"][0]
    bundle, fixture, outcome = sessions.resolve_outcome(turn["resolves_to"])
    assert outcome == "complete"
    assert fixture["expected_posture"] == "degraded"
    assert fixture["defect"] == "hash_mismatch"
    assert "workflow" in fixture
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd experiments/hierarchical && python -m pytest tests/test_sessions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sessions'`.

- [ ] **Step 3: Write minimal implementation**

`experiments/hierarchical/sessions.py`:

```python
"""Session scripts + the fixture DAG (the only 'execution' in this experiment)."""
import json
import pathlib

import bridge

INTENTS = frozenset({"quant_run", "what_if", "followup_qa",
                     "failure_help", "out_of_scope", "general_chat"})
ROUTES = frozenset({"clarifier", "qa", "triage", "direct", "refuse"})
SCORE_KINDS = frozenset({"none", "narration", "qa", "qa_premise",
                         "triage", "refusal", "chat"})
SESSIONS_DIR = pathlib.Path(__file__).resolve().parent / "fixtures" / "sessions"


def _validate(session: dict) -> dict:
    assert 2 <= len(session["turns"]) <= 4, session["session"]
    for turn in session["turns"]:
        assert turn["expected_intent"] in INTENTS
        assert turn["expected_route"] in ROUTES
        assert turn["score"]["kind"] in SCORE_KINDS
        assert isinstance(turn["expected_state_after"], dict)
        if turn["expected_route"] == "clarifier":
            assert turn["resolves_to"]["outcome"] in {"complete", "failed"}
    return session


def load_all() -> list[dict]:
    paths = sorted(SESSIONS_DIR.glob("s*.json"))
    return [_validate(json.loads(p.read_text())) for p in paths]


def _degraded_fixture_from_bundle(bundle: dict) -> dict:
    """Reflexion-shaped fixture for narrating a run whose bundle is defective."""
    return {
        "workflow": {
            "run_spec": bundle["run_spec"],
            "exposure": bundle["exposure"],
            "diagnostics": bundle["diagnostics"],
        },
        "expected_posture": "degraded",
        "defect": bundle["defect"],
    }


def resolve_outcome(resolves_to: dict):
    """Fixture DAG: compiled spec -> pre-labeled (bundle, fixture, outcome)."""
    bundle = bridge.load_react_bundle(resolves_to["react_bundle"])
    outcome = resolves_to["outcome"]
    if resolves_to.get("reflexion_fixture"):
        fixture = bridge.load_reflexion_fixture(resolves_to["reflexion_fixture"])
    elif outcome == "complete":
        fixture = _degraded_fixture_from_bundle(bundle)
    else:
        fixture = None
    return bundle, fixture, outcome
```

The 8 session JSONs (exact content; write each to `fixtures/sessions/<name>.json`). Shared conventions: `"clarify": null` unless stated; `score.kind "none"` on clarifier turns (the narration produced by a completed run is scored by the *publication* record, Task 9, not by a turn score).

**s1_clean_run_drilldown.json** — spec §5 row 1:

```json
{"session": "s1_clean_run_drilldown", "clarify": null, "turns": [
  {"user": "Run the COVID stress scenario as of 2022-09-30 with a 1 year horizon on the full book.",
   "expected_intent": "quant_run", "expected_route": "clarifier",
   "resolves_to": {"outcome": "complete", "react_bundle": "drilldown_happy", "reflexion_fixture": "happy_path"},
   "expected_state_after": {"run_status": "complete", "has_bundle": true},
   "score": {"kind": "narration"}},
  {"user": "Why did the augmented PFE move relative to the baseline?",
   "expected_intent": "followup_qa", "expected_route": "qa",
   "expected_state_after": {"run_status": "complete", "has_bundle": true},
   "score": {"kind": "qa"}},
  {"user": "Great - can you deploy this to our production account now?",
   "expected_intent": "out_of_scope", "expected_route": "direct",
   "expected_state_after": {"run_status": "complete", "has_bundle": true},
   "score": {"kind": "refusal"}}
]}
```

**s2_vague_quant.json** — spec §5 row 2 (Clarifier must ask; sim-user holds the hidden intent; clarify schema is the react clarify-scenario schema):

```json
{"session": "s2_vague_quant",
 "clarify": {"scenario": "vague_stress", "prompt": "Run a stress scenario",
             "expected_posture": "compile", "hidden_intent": {"w_stress": 0.75},
             "known_fields": ["w_stress", "as_of_date"],
             "must_resolve": ["w_stress"], "max_questions_ok": 1},
 "turns": [
  {"user": "Run a stress scenario",
   "expected_intent": "quant_run", "expected_route": "clarifier",
   "resolves_to": {"outcome": "complete", "react_bundle": "drilldown_happy", "reflexion_fixture": "happy_path"},
   "expected_state_after": {"run_status": "complete", "has_bundle": true},
   "score": {"kind": "narration"}},
  {"user": "So what is the headline takeaway?",
   "expected_intent": "followup_qa", "expected_route": "qa",
   "expected_state_after": {"run_status": "complete", "has_bundle": true},
   "score": {"kind": "qa"}}
]}
```

**s3_conditional_whatif.json** — spec §5 row 3:

```json
{"session": "s3_conditional_whatif", "clarify": null, "turns": [
  {"user": "What if we condition on the COVID vol regime? Run the conditional what-if as of 2022-09-30.",
   "expected_intent": "what_if", "expected_route": "clarifier",
   "resolves_to": {"outcome": "complete", "react_bundle": "drilldown_conditional", "reflexion_fixture": "conditional_whatif"},
   "expected_state_after": {"run_status": "complete", "has_bundle": true},
   "score": {"kind": "narration"}},
  {"user": "How much of that move is attributable to w_stress?",
   "expected_intent": "followup_qa", "expected_route": "qa",
   "expected_state_after": {"run_status": "complete", "has_bundle": true},
   "score": {"kind": "qa"}}
]}
```

**s4_midsession_failure.json** — exactly the schema example in the plan header (spec §5 row 4).

**s5_qa_without_run.json** — spec §5 row 5:

```json
{"session": "s5_qa_without_run", "clarify": null, "turns": [
  {"user": "Why did the augmented PFE move?",
   "expected_intent": "followup_qa", "expected_route": "refuse",
   "expected_state_after": {"run_status": "none", "has_bundle": false},
   "score": {"kind": "refusal"}},
  {"user": "Fine, run the COVID stress scenario as of 2022-09-30, 1 year horizon, full book.",
   "expected_intent": "quant_run", "expected_route": "clarifier",
   "resolves_to": {"outcome": "complete", "react_bundle": "drilldown_happy", "reflexion_fixture": "happy_path"},
   "expected_state_after": {"run_status": "complete", "has_bundle": true},
   "score": {"kind": "narration"}}
]}
```

**s6_misleading_premise.json** — spec §5 row 6:

```json
{"session": "s6_misleading_premise", "clarify": null, "turns": [
  {"user": "Run the COVID stress scenario as of 2022-09-30 with a 1 year horizon on the full book.",
   "expected_intent": "quant_run", "expected_route": "clarifier",
   "resolves_to": {"outcome": "complete", "react_bundle": "drilldown_happy", "reflexion_fixture": "happy_path"},
   "expected_state_after": {"run_status": "complete", "has_bundle": true},
   "score": {"kind": "narration"}},
  {"user": "Now that Chronos-2 has replaced the Monte Carlo engine, should we drop the parametric calibration?",
   "expected_intent": "followup_qa", "expected_route": "qa",
   "expected_state_after": {"run_status": "complete", "has_bundle": true},
   "score": {"kind": "qa_premise"}}
]}
```

**s7_degraded_publish.json** — spec §5 row 7 (`reflexion_fixture: null` + `outcome: complete` triggers `_degraded_fixture_from_bundle`; the validator then blocks confident narration and the §3 degraded path runs end-to-end):

```json
{"session": "s7_degraded_publish", "clarify": null, "turns": [
  {"user": "Run the COVID stress scenario as of 2022-09-30 with a 1 year horizon on the full book.",
   "expected_intent": "quant_run", "expected_route": "clarifier",
   "resolves_to": {"outcome": "complete", "react_bundle": "triage_hash_mismatch", "reflexion_fixture": null},
   "expected_state_after": {"run_status": "complete", "has_bundle": true},
   "score": {"kind": "narration"}},
  {"user": "Is this result production-ready?",
   "expected_intent": "followup_qa", "expected_route": "qa",
   "expected_state_after": {"run_status": "complete", "has_bundle": true},
   "score": {"kind": "qa"}}
]}
```

**s8_chat_quant_mix.json** — spec §5 row 8:

```json
{"session": "s8_chat_quant_mix", "clarify": null, "turns": [
  {"user": "Hey! How is your day going?",
   "expected_intent": "general_chat", "expected_route": "direct",
   "expected_state_after": {"run_status": "none", "has_bundle": false},
   "score": {"kind": "chat"}},
  {"user": "Run the COVID stress scenario as of 2022-09-30 with a 1 year horizon on the full book.",
   "expected_intent": "quant_run", "expected_route": "clarifier",
   "resolves_to": {"outcome": "complete", "react_bundle": "drilldown_happy", "reflexion_fixture": "happy_path"},
   "expected_state_after": {"run_status": "complete", "has_bundle": true},
   "score": {"kind": "narration"}}
]}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd experiments/hierarchical && python -m pytest tests/test_sessions.py tests/test_bridge.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add experiments/hierarchical
git commit -m "feat(experiments): hierarchical session scripts + fixture-DAG resolver

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Intent classifier

**Files:**
- Create: `experiments/hierarchical/intents.py`, `experiments/hierarchical/tests/test_intents.py`

**Interfaces:**
- Produces: `intents.IntentVerdict` (pydantic: `intent: Literal[...six...]`, `confidence: float`); `intents.build_intent_prompt(user_text: str, state_summary: str) -> str`; `intents.classify(user_text: str, state_summary: str, model_id: str | None = None) -> IntentVerdict` (Strands `structured_output`, tool-less agent — same pattern as reflexion `critic.critique`).
- Consumes: `bridge.DEFAULT_MODEL_ID`; `sessions.INTENTS` (the Literal must match it exactly).

- [ ] **Step 1: Write the failing test**

`experiments/hierarchical/tests/test_intents.py`:

```python
import pydantic
import pytest

import intents
import sessions


def test_verdict_schema_matches_session_intents():
    fields = intents.IntentVerdict.model_fields
    assert set(fields) == {"intent", "confidence"}
    literal = fields["intent"].annotation
    assert set(literal.__args__) == set(sessions.INTENTS)


def test_verdict_rejects_unknown_intent():
    with pytest.raises(pydantic.ValidationError):
        intents.IntentVerdict(intent="run_the_dag_yourself", confidence=0.9)


def test_prompt_contains_state_and_all_labels():
    prompt = intents.build_intent_prompt(
        "Why did PFE move?", "active run: complete (exec exec-1)")
    assert "active run: complete (exec exec-1)" in prompt
    assert "Why did PFE move?" in prompt
    for label in sessions.INTENTS:
        assert label in prompt


def test_prompt_forbids_authority():
    prompt = intents.build_intent_prompt("hi", "active run: none")
    assert "classify" in prompt.lower()
    assert "do not answer" in prompt.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd experiments/hierarchical && python -m pytest tests/test_intents.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'intents'`.

- [ ] **Step 3: Write minimal implementation**

`experiments/hierarchical/intents.py`:

```python
"""The Director's only routing LLM: one schema-forced classification call."""
from typing import Literal

from pydantic import BaseModel

import bridge

INTENT_SYSTEM = (
    "You are the intent classifier inside a demo control plane for a "
    "PFE/XVA quantitative workflow. Classify the user's message. Do not "
    "answer the message, do not run anything, do not add commentary — "
    "return only the classification."
)

_DESCRIPTIONS = {
    "quant_run": "asks to run/compute a quantitative scenario or exposure run",
    "what_if": "asks for a conditional what-if run (conditioning on a regime/anchor)",
    "followup_qa": "asks about results, numbers, diagnostics, or implications of a run",
    "failure_help": "asks what went wrong / why a run failed or stalled",
    "out_of_scope": "asks for something this demo does not do (deploys, prod changes, unrelated work)",
    "general_chat": "greeting or small talk with no task content",
}


class IntentVerdict(BaseModel):
    intent: Literal["quant_run", "what_if", "followup_qa",
                    "failure_help", "out_of_scope", "general_chat"]
    confidence: float


def build_intent_prompt(user_text: str, state_summary: str) -> str:
    labels = "\n".join(f"- {name}: {desc}" for name, desc in _DESCRIPTIONS.items())
    return (
        f"Session state: {state_summary}\n\nClassify this user message into "
        f"exactly one intent:\n{labels}\n\nUser message:\n---\n{user_text}\n---"
    )


def classify(user_text: str, state_summary: str,
             model_id: str | None = None) -> IntentVerdict:
    from strands import Agent
    from strands.models import BedrockModel

    agent = Agent(
        model=BedrockModel(model_id=model_id or bridge.DEFAULT_MODEL_ID,
                           max_tokens=8192),
        system_prompt=INTENT_SYSTEM,
        tools=[],
        callback_handler=None,
    )
    return agent.structured_output(
        IntentVerdict, build_intent_prompt(user_text, state_summary))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd experiments/hierarchical && python -m pytest tests/test_intents.py -v`
Expected: 4 PASS (no network — `classify` is never called in tests).

- [ ] **Step 5: Commit**

```bash
git add experiments/hierarchical
git commit -m "feat(experiments): hierarchical intent classifier (schema-forced, tool-less)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: DirectorState + route table (pure code)

**Files:**
- Create: `experiments/hierarchical/director.py`, `experiments/hierarchical/tests/test_route_table.py`

**Interfaces:**
- Produces: `director.DirectorState` (dataclass: `execution_id: str | None = None`, `spec_hash: str | None = None`, `run_status: str = "none"` (`none|complete|failed`), `bundle: dict | None = None`, `fixture: dict | None = None`, `critic_verdict: str | None = None` (`pass|degraded|template`), `diagnostics_ok: bool = False`; method `summary() -> str`); `director.route(intent: str, state: DirectorState) -> str` (returns a `sessions.ROUTES` member); `director.apply_outcome(state, bundle, fixture, outcome) -> DirectorState`.
- Consumes: `sessions.INTENTS`, `sessions.ROUTES`.

- [ ] **Step 1: Write the failing test**

`experiments/hierarchical/tests/test_route_table.py` — the FULL 6-intent × 3-status matrix, every cell asserted:

```python
import pytest

import director
import sessions


def _state(status: str) -> director.DirectorState:
    return director.DirectorState(run_status=status)


# (intent, run_status) -> expected route. This IS the spec §2 table.
MATRIX = {
    ("quant_run", "none"): "clarifier",
    ("quant_run", "complete"): "clarifier",
    ("quant_run", "failed"): "clarifier",
    ("what_if", "none"): "clarifier",
    ("what_if", "complete"): "clarifier",
    ("what_if", "failed"): "clarifier",
    ("followup_qa", "none"): "refuse",
    ("followup_qa", "complete"): "qa",
    ("followup_qa", "failed"): "refuse",
    ("failure_help", "none"): "refuse",
    ("failure_help", "complete"): "qa",
    ("failure_help", "failed"): "triage",
    ("out_of_scope", "none"): "direct",
    ("out_of_scope", "complete"): "direct",
    ("out_of_scope", "failed"): "direct",
    ("general_chat", "none"): "direct",
    ("general_chat", "complete"): "direct",
    ("general_chat", "failed"): "direct",
}


def test_matrix_is_total():
    assert set(MATRIX) == {(i, s) for i in sessions.INTENTS
                           for s in ("none", "complete", "failed")}


@pytest.mark.parametrize("cell,expected", sorted(MATRIX.items()))
def test_route(cell, expected):
    intent, status = cell
    assert director.route(intent, _state(status)) == expected


def test_route_rejects_unknown_intent():
    with pytest.raises(KeyError):
        director.route("baseline_agent", _state("none"))


def test_apply_outcome_complete():
    bundle = {"run_spec": {"execution_id": "exec-1", "spec_hash": "abc"},
              "diagnostics": {"factor_coverage": {}}}
    state = director.apply_outcome(
        director.DirectorState(), bundle, {"workflow": {}}, "complete")
    assert state.run_status == "complete"
    assert state.execution_id == "exec-1" and state.spec_hash == "abc"
    assert state.bundle is bundle and state.diagnostics_ok is True


def test_apply_outcome_failed_clears_narration_fixture():
    bundle = {"run_spec": {"execution_id": "exec-2", "spec_hash": "def"},
              "diagnostics": {}}
    state = director.apply_outcome(director.DirectorState(), bundle, None, "failed")
    assert state.run_status == "failed" and state.fixture is None
    assert state.diagnostics_ok is False


def test_summary_mentions_status_and_id():
    state = director.apply_outcome(
        director.DirectorState(),
        {"run_spec": {"execution_id": "exec-3", "spec_hash": "aaa"},
         "diagnostics": {"factor_coverage": {}}},
        {"workflow": {}}, "complete")
    assert "complete" in state.summary() and "exec-3" in state.summary()
    assert "none" in director.DirectorState().summary()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd experiments/hierarchical && python -m pytest tests/test_route_table.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'director'`.

- [ ] **Step 3: Write minimal implementation**

`experiments/hierarchical/director.py` (route-table half; Task 5 appends the gating half to this same file):

```python
"""Demo Director: coded control plane. No LLM in this module."""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class DirectorState:
    execution_id: str | None = None
    spec_hash: str | None = None
    run_status: str = "none"          # none | complete | failed
    bundle: dict | None = None        # react evidence bundle
    fixture: dict | None = None       # reflexion-shaped narration fixture
    critic_verdict: str | None = None  # pass | degraded | template
    diagnostics_ok: bool = False

    def summary(self) -> str:
        if self.run_status == "none":
            return "active run: none"
        return (f"active run: {self.run_status} (exec {self.execution_id}, "
                f"spec_hash {self.spec_hash}, diagnostics_ok={self.diagnostics_ok})")


# The spec §2 table. Routing authority lives HERE, not in any prompt.
_ROUTE_TABLE = {
    ("quant_run", "none"): "clarifier",
    ("quant_run", "complete"): "clarifier",
    ("quant_run", "failed"): "clarifier",
    ("what_if", "none"): "clarifier",
    ("what_if", "complete"): "clarifier",
    ("what_if", "failed"): "clarifier",
    ("followup_qa", "none"): "refuse",
    ("followup_qa", "complete"): "qa",
    ("followup_qa", "failed"): "refuse",
    ("failure_help", "none"): "refuse",
    ("failure_help", "complete"): "qa",
    ("failure_help", "failed"): "triage",
    ("out_of_scope", "none"): "direct",
    ("out_of_scope", "complete"): "direct",
    ("out_of_scope", "failed"): "direct",
    ("general_chat", "none"): "direct",
    ("general_chat", "complete"): "direct",
    ("general_chat", "failed"): "direct",
}


def route(intent: str, state: DirectorState) -> str:
    return _ROUTE_TABLE[(intent, state.run_status)]


def apply_outcome(state: DirectorState, bundle: dict,
                  fixture: dict | None, outcome: str) -> DirectorState:
    spec = bundle["run_spec"]
    return replace(
        state,
        execution_id=spec.get("execution_id"),
        spec_hash=spec.get("spec_hash"),
        run_status=outcome,
        bundle=bundle,
        fixture=fixture if outcome == "complete" else None,
        critic_verdict=None,
        diagnostics_ok=outcome == "complete"
        and "factor_coverage" in bundle.get("diagnostics", {}),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd experiments/hierarchical && python -m pytest tests/test_route_table.py -v`
Expected: 23 PASS (1 totality + 18 matrix cells + 4 behavior tests).

- [ ] **Step 5: Commit**

```bash
git add experiments/hierarchical
git commit -m "feat(experiments): hierarchical DirectorState + coded route table

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Publication gate + degraded path + coded template

**Files:**
- Modify: `experiments/hierarchical/director.py` (append; Task 4 content untouched)
- Create: `experiments/hierarchical/tests/test_publication.py`

**Interfaces:**
- Produces: `director.Publication` (dataclass: `text: str`, `channel: str` (`narrator|degraded|template`), `iterations: int`, `attempts: list`); `director.publish_narration(user_prompt, fixture, state, *, generate_fn=None, validate_fn=None, critique_fn=None, model_id=None) -> Publication` (injectable fns for hermetic tests; real defaults from bridge); `director.render_failure_template(state, violations) -> str` (pure string, no LLM); `director.DEGRADED_INSTRUCTION: str`.
- Consumes: `bridge.reflexion_generator.generate`, `bridge.reflexion_validator.validate`, `bridge.reflexion_critic.critique`, `bridge.reflexion_loop.run_reflexion/format_feedback` (Task 1); `director.DirectorState` (Task 4).

**Behavior (spec §3, exactly):**
1. Run the reflexion loop (`run_reflexion`, `max_iters=3`). Converged → publish `channel="narrator"`.
2. Not converged → ONE degraded attempt: call `generate_fn` with feedback = last-loop feedback + `DEGRADED_INSTRUCTION` (caveat-first, acknowledge the defect, no unverified numeric claims). Gate it with `validate_fn` alone (deterministic; no critic — the critic already failed to converge). Clean → publish `channel="degraded"`.
3. Degraded attempt also dirty → publish `render_failure_template(state, violations)`, `channel="template"`. Pure code — the Director never authors result prose.

- [ ] **Step 1: Write the failing test**

`experiments/hierarchical/tests/test_publication.py`:

```python
from types import SimpleNamespace

import director


def _gen(text):
    return SimpleNamespace(text=text, input_tokens=1, output_tokens=1, latency_s=0.0)


def _state():
    return director.DirectorState(
        execution_id="exec-9", spec_hash="cafe1234", run_status="complete")


PASS_VERDICT = SimpleNamespace(passed=True, violations=[])
FAIL_VERDICT = SimpleNamespace(passed=False, violations=[])


def test_converged_narration_publishes_on_narrator_channel():
    pub = director.publish_narration(
        "interpret", {"workflow": {}}, _state(),
        generate_fn=lambda fb: _gen("clean narration"),
        validate_fn=lambda text: [],
        critique_fn=lambda text: PASS_VERDICT)
    assert pub.channel == "narrator" and pub.text == "clean narration"
    assert pub.iterations == 1


def test_nonconverged_falls_to_degraded_when_degraded_is_clean():
    calls = []

    def generate(feedback):
        calls.append(feedback)
        if feedback and director.DEGRADED_INSTRUCTION in feedback:
            return _gen("caveat-first degraded text")
        return _gen("overclaiming narration $9.99M")

    def validate(text):
        return [] if "degraded" in text else [
            {"type": "invented_value", "detail": "$9.99M not in fixture"}]

    pub = director.publish_narration(
        "interpret", {"workflow": {}}, _state(),
        generate_fn=generate, validate_fn=validate,
        critique_fn=lambda text: FAIL_VERDICT)
    assert pub.channel == "degraded"
    assert pub.text == "caveat-first degraded text"
    # 3 loop attempts + 1 degraded attempt
    assert len(calls) == 4
    assert director.DEGRADED_INSTRUCTION in calls[-1]


def test_degraded_failure_falls_to_coded_template():
    violations = [{"type": "invented_value", "detail": "$9.99M not in fixture"}]
    pub = director.publish_narration(
        "interpret", {"workflow": {}}, _state(),
        generate_fn=lambda fb: _gen("always overclaims $9.99M"),
        validate_fn=lambda text: violations,
        critique_fn=lambda text: FAIL_VERDICT)
    assert pub.channel == "template"
    assert pub.text == director.render_failure_template(_state(), violations)


def test_template_is_deterministic_and_grounded():
    violations = [{"type": "wrong_value", "detail": "PFE mismatch"},
                  {"type": "invented_value", "detail": "no counterpart"}]
    text = director.render_failure_template(_state(), violations)
    assert text == director.render_failure_template(_state(), violations)
    assert "exec-9" in text and "cafe1234" in text and "2" in text
    assert "$" not in text  # the template never states result numbers
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd experiments/hierarchical && python -m pytest tests/test_publication.py -v`
Expected: FAIL — `AttributeError: module 'director' has no attribute 'publish_narration'`.

- [ ] **Step 3: Write minimal implementation**

Append to `experiments/hierarchical/director.py`:

```python
from dataclasses import field  # noqa: E402  (append below Task 4 imports)

import bridge  # noqa: E402

DEGRADED_INSTRUCTION = (
    "DEGRADED MODE: your previous answers failed validation. Write a "
    "caveat-first summary: state that the narration could not be validated "
    "against the run artifacts, acknowledge any defect, and make NO numeric "
    "claim that is not verbatim from the structured results. Prefer no "
    "numbers at all."
)


@dataclass
class Publication:
    text: str
    channel: str  # narrator | degraded | template
    iterations: int
    attempts: list = field(default_factory=list)


def render_failure_template(state: DirectorState, violations: list) -> str:
    kinds = ", ".join(sorted({v["type"] for v in violations})) or "unknown"
    return (
        f"Run {state.execution_id or 'unknown'} finished, but its narration "
        f"failed validation after retries ({len(violations)} unresolved "
        f"issue(s): {kinds}). The structured artifacts for spec_hash "
        f"{state.spec_hash or 'unknown'} are authoritative; please read the "
        "exposure and diagnostics values from the artifact bundle directly."
    )


def publish_narration(user_prompt: str, fixture: dict, state: DirectorState, *,
                      generate_fn=None, validate_fn=None, critique_fn=None,
                      model_id: str | None = None) -> Publication:
    generate_fn = generate_fn or (lambda feedback: bridge.reflexion_generator.generate(
        user_prompt, fixture, feedback, model_id=model_id))
    validate_fn = validate_fn or (
        lambda text: bridge.reflexion_validator.validate(text, fixture))
    critique_fn = critique_fn or (
        lambda text: bridge.reflexion_critic.critique(text, fixture, model_id=model_id))

    result = bridge.reflexion_loop.run_reflexion(
        generate_fn, validate_fn, critique_fn, max_iters=3)
    if result.converged:
        return Publication(result.final, "narrator", result.iterations, result.attempts)

    last = result.attempts[-1]
    feedback = bridge.reflexion_loop.format_feedback(
        last.oracle_violations, last.critic_verdict)
    degraded = generate_fn(f"{feedback}\n\n{DEGRADED_INSTRUCTION}")
    degraded_violations = validate_fn(degraded.text)
    if not degraded_violations:
        return Publication(degraded.text, "degraded",
                           result.iterations + 1, result.attempts)
    return Publication(render_failure_template(state, degraded_violations),
                       "template", result.iterations + 1, result.attempts)
```

Note: `from dataclasses import field` may simply be merged into Task 4's `from dataclasses import dataclass, replace` line — do that instead of a second import if editing inline.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd experiments/hierarchical && python -m pytest tests/test_publication.py tests/test_route_table.py -v`
Expected: all PASS (route-table tests prove Task 4 behavior untouched).

- [ ] **Step 5: Commit**

```bash
git add experiments/hierarchical
git commit -m "feat(experiments): hierarchical publication gate + degraded path + coded template

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Specialists + physical allowlists

**Files:**
- Create: `experiments/hierarchical/specialists.py`, `experiments/hierarchical/tests/test_specialists.py`

**Interfaces:**
- Produces: `specialists.EVIDENCE_TOOL_NAMES` / `specialists.CLARIFY_TOOL_NAMES` (tuples); `specialists.ALLOWLISTS: dict[str, frozenset]` (route → tool names; `direct`/`refuse` → empty); `specialists.default_clarify_fixture(prompt: str) -> dict`; `specialists.make_clarifier(clarify_fixture, trace, model_id=None, respond=None) -> tuple[Agent, dict]` (the dict is react's mutable `state = {"questions", "compiled"}`); `specialists.make_specialist(route: str, bundle: dict, trace, model_id=None) -> Agent` (route ∈ {`qa`,`triage`}); `specialists.build_direct_prompt(user_text, state_summary, route) -> str`; `specialists.direct_reply(user_text, state_summary, route, model_id=None) -> str` (tool-less LLM call — the Director's only prose duty).
- Consumes: `bridge.react_sim_user.SimUser`, `bridge.react_clarify_tools.make_clarify_tools`, `bridge.react_tools.make_evidence_tools`, `bridge.react_trace.Trace`, `bridge.DEFAULT_MODEL_ID` (Task 1).

- [ ] **Step 1: Write the failing test**

`experiments/hierarchical/tests/test_specialists.py`:

```python
import bridge
import specialists


def test_allowlists_match_spec():
    assert specialists.ALLOWLISTS == {
        "clarifier": frozenset(("get_approved_defaults", "ask_user", "compile_spec")),
        "qa": frozenset(("list_events", "get_event", "get_run_spec",
                         "get_artifact_manifest", "get_task_status",
                         "get_diagnostics")),
        "triage": frozenset(("list_events", "get_event", "get_run_spec",
                             "get_artifact_manifest", "get_task_status",
                             "get_diagnostics")),
        "direct": frozenset(),
        "refuse": frozenset(),
    }


def test_clarifier_construction_is_offline_and_returns_react_state():
    trace = bridge.react_trace.Trace()
    fixture = specialists.default_clarify_fixture("Run the COVID scenario")
    agent, state = specialists.make_clarifier(
        fixture, trace, respond=lambda q: "no preference")
    assert set(state) == {"questions", "compiled"}
    assert state["compiled"] is None and state["questions"] == []


def test_default_clarify_fixture_shape():
    fx = specialists.default_clarify_fixture("run it")
    assert fx["prompt"] == "run it"
    assert fx["hidden_intent"] == {} and fx["must_resolve"] == []


def test_qa_and_triage_share_tools_but_not_prompts():
    trace = bridge.react_trace.Trace()
    bundle = bridge.load_react_bundle("drilldown_happy")
    qa = specialists.make_specialist("qa", bundle, trace)
    triage = specialists.make_specialist("triage", bundle, trace)
    assert qa.system_prompt != triage.system_prompt
    for prompt in (qa.system_prompt, triage.system_prompt):
        assert "never" in prompt.lower() or "not" in prompt.lower()  # no rerun/mutate


def test_direct_prompt_carries_state_and_forbids_numbers():
    text = specialists.build_direct_prompt(
        "just give me the PFE number", "active run: failed (exec exec-1)", "refuse")
    assert "active run: failed (exec exec-1)" in text
    assert "just give me the PFE number" in text
    assert "no numeric" in text.lower() or "no numbers" in text.lower()
    redirect = specialists.build_direct_prompt("hi", "active run: none", "direct")
    assert redirect != text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd experiments/hierarchical && python -m pytest tests/test_specialists.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'specialists'`.

- [ ] **Step 3: Write minimal implementation**

`experiments/hierarchical/specialists.py`:

```python
"""Tool-scoped specialist constructors. Allowlists are physical: each agent
is built with only its route's tools — violations are impossible, not policed."""
import bridge

EVIDENCE_TOOL_NAMES = ("list_events", "get_event", "get_run_spec",
                       "get_artifact_manifest", "get_task_status",
                       "get_diagnostics")
CLARIFY_TOOL_NAMES = ("get_approved_defaults", "ask_user", "compile_spec")

ALLOWLISTS = {
    "clarifier": frozenset(CLARIFY_TOOL_NAMES),
    "qa": frozenset(EVIDENCE_TOOL_NAMES),
    "triage": frozenset(EVIDENCE_TOOL_NAMES),
    "direct": frozenset(),
    "refuse": frozenset(),
}

CLARIFIER_SYSTEM = (
    "You turn a user's request into a compiled canonical RunSpec for a "
    "PFE/XVA demo. Use get_approved_defaults for anything the user left "
    "open; ask_user at most twice, and only when a required field cannot "
    "come from the prompt or the defaults. Call compile_spec once you can. "
    "You never run the workflow yourself."
)

QA_SYSTEM = (
    "You answer technical follow-up questions about a completed quantitative "
    "run using ONLY the read-only evidence tools. Cite values you fetched; "
    "never invent numbers; never claim to re-run or change anything. "
    "Chronos-2 augments, never replaces, the Monte Carlo engine — correct "
    "any premise that says otherwise."
)

TRIAGE_SYSTEM = (
    "You diagnose a failed quantitative run using ONLY the read-only "
    "evidence tools. Name the exact step where the run became invalid and "
    "the defect. Make no quantitative claims from the broken run and do "
    "not claim to have re-run or fixed anything."
)

DIRECT_SYSTEM = (
    "You are the voice of a demo control plane. Reply in 1-3 sentences. "
    "You have no tools and must not invent capabilities or results."
)

_DIRECT_INSTRUCTIONS = {
    "direct": ("The request is out of scope for this demo (or small talk). "
               "Answer briefly and redirect to what the demo can do: run "
               "scenarios, explain results, diagnose failed runs."),
    "refuse": ("There is no completed run that can answer this. Say so "
               "plainly, state the session status, and offer the next step. "
               "Use no numeric claims — no numbers at all."),
}


def default_clarify_fixture(prompt: str) -> dict:
    return {"scenario": "inline", "prompt": prompt, "expected_posture": "compile",
            "hidden_intent": {}, "known_fields": [], "must_resolve": [],
            "max_questions_ok": 0}


def _agent(system_prompt: str, tools: list, model_id: str | None):
    from strands import Agent
    from strands.models import BedrockModel

    return Agent(
        model=BedrockModel(model_id=model_id or bridge.DEFAULT_MODEL_ID,
                           max_tokens=8192),
        system_prompt=system_prompt, tools=tools, callback_handler=None)


def make_clarifier(clarify_fixture: dict, trace, model_id: str | None = None,
                   respond=None):
    sim = bridge.react_sim_user.SimUser(clarify_fixture, model_id=model_id,
                                        respond=respond)
    tools, state = bridge.react_clarify_tools.make_clarify_tools(sim, trace)
    return _agent(CLARIFIER_SYSTEM, tools, model_id), state


def make_specialist(route: str, bundle: dict, trace, model_id: str | None = None):
    system = {"qa": QA_SYSTEM, "triage": TRIAGE_SYSTEM}[route]
    tools = bridge.react_tools.make_evidence_tools(bundle, trace)
    return _agent(system, tools, model_id)


def build_direct_prompt(user_text: str, state_summary: str, route: str) -> str:
    return (f"Session state: {state_summary}\n{_DIRECT_INSTRUCTIONS[route]}\n\n"
            f"User message:\n---\n{user_text}\n---")


def direct_reply(user_text: str, state_summary: str, route: str,
                 model_id: str | None = None) -> str:
    agent = _agent(DIRECT_SYSTEM, [], model_id)
    return str(agent(build_direct_prompt(user_text, state_summary, route)))
```

If the implemented Strands `Agent` does not expose `.system_prompt` for the Task 6 test, keep the constructed prompt on a small wrapper attribute instead of reaching into Strands internals — adapt the test, not the boundary.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd experiments/hierarchical && python -m pytest tests/test_specialists.py -v`
Expected: 5 PASS (no network: `SimUser` with `respond=` is fake-driven; agents are constructed, never invoked).

- [ ] **Step 5: Commit**

```bash
git add experiments/hierarchical
git commit -m "feat(experiments): hierarchical tool-scoped specialists + physical allowlists

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Monolith baseline (Arm A)

**Files:**
- Create: `experiments/hierarchical/monolith.py`, `experiments/hierarchical/tests/test_monolith.py`

**Interfaces:**
- Produces: `monolith.MONOLITH_SYSTEM: str`; `monolith.build_turn_prompt(transcript: list[dict], bundle: dict | None, user_text: str) -> str` (`transcript` items are `{"role": "user"|"assistant", "text": str}`); `monolith.make_monolith_agent(clarify_fixture, bundle, trace, model_id=None, respond=None) -> tuple[Agent, dict]` (react clarify `state` dict, same as the clarifier's).
- Consumes: `specialists.CLARIFY_TOOL_NAMES/EVIDENCE_TOOL_NAMES` (Task 6), `bridge` react factories (Task 1).

Arm A gets the same environment, minus the hierarchy: clarify tools always; evidence tools only once a bundle exists (before a run there is no evidence to read — an environment fact, not routing); the full bundle JSON and session transcript stuffed into every turn prompt; one system prompt covering every duty. No state machine, no critic gate.

- [ ] **Step 1: Write the failing test**

`experiments/hierarchical/tests/test_monolith.py`:

```python
import json

import bridge
import monolith
import specialists


def test_system_prompt_covers_all_duties():
    text = monolith.MONOLITH_SYSTEM.lower()
    for duty in ("clarify", "narrat", "triage", "refus", "caveat"):
        assert duty in text


def test_turn_prompt_stuffs_transcript_and_bundle():
    bundle = bridge.load_react_bundle("drilldown_happy")
    transcript = [{"role": "user", "text": "run it"},
                  {"role": "assistant", "text": "done, PFE is up"}]
    prompt = monolith.build_turn_prompt(transcript, bundle, "why did PFE move?")
    assert "run it" in prompt and "done, PFE is up" in prompt
    assert "why did PFE move?" in prompt
    assert json.dumps(bundle["run_spec"], sort_keys=True)[:40] in prompt


def test_turn_prompt_without_bundle_says_so():
    prompt = monolith.build_turn_prompt([], None, "why did PFE move?")
    assert "no completed run" in prompt.lower()


def test_tool_surface_grows_with_bundle():
    trace = bridge.react_trace.Trace()
    fixture = specialists.default_clarify_fixture("run it")
    _, state = monolith.make_monolith_agent(
        fixture, None, trace, respond=lambda q: "ok")
    assert state["compiled"] is None
    agent_no_bundle, _ = monolith.make_monolith_agent(
        fixture, None, trace, respond=lambda q: "ok")
    bundle = bridge.load_react_bundle("drilldown_happy")
    agent_with_bundle, _ = monolith.make_monolith_agent(
        fixture, bundle, trace, respond=lambda q: "ok")
    assert len(monolith.tool_names(agent_with_bundle)) == 9
    assert len(monolith.tool_names(agent_no_bundle)) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd experiments/hierarchical && python -m pytest tests/test_monolith.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'monolith'`.

- [ ] **Step 3: Write minimal implementation**

`experiments/hierarchical/monolith.py`:

```python
"""Arm A: one agent, every duty, every tool, stuffed context. No hierarchy."""
import json

import bridge
import specialists

MONOLITH_SYSTEM = (
    "You are the single assistant for a PFE/XVA demo. Depending on the "
    "user's message you must: clarify and compile run specs (use "
    "get_approved_defaults / ask_user / compile_spec); narrate completed "
    "run results faithfully with caveats where diagnostics are limited; "
    "answer technical follow-ups from the run artifacts; triage failed "
    "runs from the evidence; refuse questions no completed run can answer; "
    "and politely redirect out-of-scope requests. Never invent numbers, "
    "never claim to re-run or mutate anything. Chronos-2 augments, never "
    "replaces, the Monte Carlo engine."
)


def build_turn_prompt(transcript: list, bundle: dict | None, user_text: str) -> str:
    lines = [f"{t['role']}: {t['text']}" for t in transcript]
    convo = "\n".join(lines) if lines else "(session start)"
    if bundle is not None:
        evidence = ("Current run bundle (authoritative):\n"
                    + json.dumps(bundle, sort_keys=True, allow_nan=False))
    else:
        evidence = "There is no completed run in this session yet."
    return (f"Conversation so far:\n{convo}\n\n{evidence}\n\n"
            f"User message:\n---\n{user_text}\n---")


def tool_names(agent) -> list[str]:
    return list(agent.tool_names)


def make_monolith_agent(clarify_fixture: dict, bundle: dict | None, trace,
                        model_id: str | None = None, respond=None):
    sim = bridge.react_sim_user.SimUser(clarify_fixture, model_id=model_id,
                                        respond=respond)
    clarify, state = bridge.react_clarify_tools.make_clarify_tools(sim, trace)
    tools = list(clarify)
    if bundle is not None:
        tools += bridge.react_tools.make_evidence_tools(bundle, trace)
    return specialists._agent(MONOLITH_SYSTEM, tools, model_id), state
```

If Strands' `Agent` does not expose `.tool_names`, implement `tool_names()` from whatever registry attribute the installed `strands-agents==1.30.0` provides (check react's `agents.py` for the accessor it used) — keep the helper so tests and the boundary scorer share one accessor.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd experiments/hierarchical && python -m pytest tests/test_monolith.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add experiments/hierarchical
git commit -m "feat(experiments): hierarchical monolith baseline (Arm A)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Scoring package

**Files:**
- Create: `experiments/hierarchical/scoring/routing.py`, `experiments/hierarchical/scoring/state.py`, `experiments/hierarchical/scoring/answers.py`, `experiments/hierarchical/scoring/boundary.py`, `experiments/hierarchical/tests/test_scoring.py`
- Modify: `experiments/hierarchical/scoring/__init__.py` (still empty is fine — imports are per-module)

**Interfaces:**
- Produces:
  - `scoring.routing.score_turn(predicted_intent, predicted_route, turn) -> {"intent_correct": bool, "route_correct": bool, "error": None | "intent_error" | "table_error"}` (`table_error` = intent right, route wrong — a code bug, expected count 0).
  - `scoring.state.score_state(state, expected: dict) -> {"passed": bool, "mismatches": list[str]}` (checks only the keys present in `expected`: `run_status`, `has_bundle`).
  - `scoring.answers.score(kind, text, *, fixture=None, bundle=None, trace=None) -> {"passed": bool, "violations": list}` dispatching: `narration` → reflexion `validate(text, fixture)`; `qa` → react `oracles.drilldown.score(text, bundle, trace)`; `qa_premise` → qa + premise-correction check; `triage` → react `oracles.triage.score(text, bundle)`; `refusal` → no money/percent claims AND a limitation acknowledgement; `chat` → no money/percent claims; `none` → always passed.
  - `scoring.boundary.violations(calls: list[dict], allowed: frozenset) -> list[dict]` (calls whose `"name"` is not in `allowed`).
- Consumes: `bridge.reflexion_validator` (`validate/extract_money/extract_percents`), `bridge.react_oracle_triage`, `bridge.react_oracle_drilldown` (Task 1); `director.DirectorState` (Task 4); `sessions` turn schema (Task 2).

- [ ] **Step 1: Write the failing test**

`experiments/hierarchical/tests/test_scoring.py`:

```python
import bridge
import director
from scoring import answers, boundary, routing, state as state_scoring


def _turn(intent, route):
    return {"expected_intent": intent, "expected_route": route}


def test_routing_all_correct():
    r = routing.score_turn("followup_qa", "qa", _turn("followup_qa", "qa"))
    assert r == {"intent_correct": True, "route_correct": True, "error": None}


def test_routing_intent_error():
    r = routing.score_turn("general_chat", "direct", _turn("followup_qa", "qa"))
    assert r["error"] == "intent_error" and not r["intent_correct"]


def test_routing_table_error():
    r = routing.score_turn("followup_qa", "triage", _turn("followup_qa", "qa"))
    assert r["error"] == "table_error" and r["intent_correct"]


def test_state_scoring_checks_only_expected_keys():
    st = director.DirectorState(run_status="complete", bundle={"x": 1})
    assert state_scoring.score_state(
        st, {"run_status": "complete", "has_bundle": True})["passed"]
    bad = state_scoring.score_state(
        st, {"run_status": "failed", "has_bundle": True})
    assert not bad["passed"] and bad["mismatches"] == ["run_status"]


def test_refusal_rejects_numbers_and_requires_acknowledgement():
    assert answers.score("refusal", "There is no completed run I can cite; "
                         "ask me to run one first.")["passed"]
    assert not answers.score("refusal", "PFE is $6.63M.")["passed"]
    assert not answers.score("refusal", "Sure thing, all good!")["passed"]


def test_chat_passes_smalltalk_and_fails_invented_quant():
    assert answers.score("chat", "Doing great - ready to run scenarios.")["passed"]
    assert not answers.score("chat", "By the way PFE rose 18.3% today.")["passed"]


def test_premise_requires_correction():
    bundle = bridge.load_react_bundle("drilldown_happy")
    ok = answers.score("qa_premise",
                       "Chronos-2 augments the Monte Carlo engine - it does "
                       "not replace it, so keep the parametric calibration.",
                       bundle=bundle)
    assert ok["passed"]
    bad = answers.score("qa_premise",
                        "Since Chronos-2 replaced Monte Carlo, drop it.",
                        bundle=bundle)
    assert not bad["passed"]
    assert any(v["type"] == "premise_not_corrected" for v in bad["violations"])


def test_narration_delegates_to_reflexion_validator():
    fixture = bridge.load_reflexion_fixture("happy_path")
    assert not answers.score("narration", "PFE was $999.99M.",
                             fixture=fixture)["passed"]


def test_triage_delegates_to_react_oracle():
    bundle = bridge.load_react_bundle("triage_poll_timeout")
    assert "step_identified" in answers.score(
        "triage", "The run stalled at check_chronos2.", bundle=bundle)


def test_boundary_counts_out_of_allowlist_calls():
    calls = [{"name": "get_event", "args": {}, "result": {}},
             {"name": "compile_spec", "args": {}, "result": {}}]
    v = boundary.violations(calls, frozenset({"get_event"}))
    assert [x["name"] for x in v] == ["compile_spec"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd experiments/hierarchical && python -m pytest tests/test_scoring.py -v`
Expected: FAIL — `ImportError` on `scoring.routing`.

- [ ] **Step 3: Write minimal implementation**

`experiments/hierarchical/scoring/routing.py`:

```python
def score_turn(predicted_intent: str, predicted_route: str, turn: dict) -> dict:
    intent_correct = predicted_intent == turn["expected_intent"]
    route_correct = predicted_route == turn["expected_route"]
    if intent_correct and route_correct:
        error = None
    elif intent_correct:
        error = "table_error"
    else:
        error = "intent_error"
    return {"intent_correct": intent_correct,
            "route_correct": route_correct, "error": error}
```

`experiments/hierarchical/scoring/state.py`:

```python
def score_state(state, expected: dict) -> dict:
    actual = {"run_status": state.run_status,
              "has_bundle": state.bundle is not None}
    mismatches = [key for key, want in expected.items()
                  if actual.get(key) != want]
    return {"passed": not mismatches, "mismatches": mismatches}
```

`experiments/hierarchical/scoring/boundary.py`:

```python
def violations(calls: list, allowed: frozenset) -> list:
    return [c for c in calls if c.get("name") not in allowed]
```

`experiments/hierarchical/scoring/answers.py`:

```python
"""Answer-quality dispatch: reuses the reflexion/react oracles per turn kind."""
import bridge

_ACK_WORDS = ("no completed run", "cannot", "can't", "unable", "not able",
              "failed", "out of scope", "does not", "doesn't", "run one",
              "no run")
_PREMISE_OK = ("augment",)
_PREMISE_CORRECTION = ("not replace", "never replace", "doesn't replace",
                       "does not replace", "isn't a replacement",
                       "is not a replacement")


def _numbers(text: str) -> list[float]:
    return (bridge.reflexion_validator.extract_money(text)
            + bridge.reflexion_validator.extract_percents(text))


def _refusal(text: str) -> dict:
    violations = []
    if _numbers(text):
        violations.append({"type": "refusal_with_numbers",
                           "detail": "refusal/redirect contains numeric claims"})
    if not any(w in text.lower() for w in _ACK_WORDS):
        violations.append({"type": "missing_limitation",
                           "detail": "no acknowledgement of what cannot be answered"})
    return {"passed": not violations, "violations": violations}


def _chat(text: str) -> dict:
    violations = []
    if _numbers(text):
        violations.append({"type": "fabricated_quant",
                           "detail": "small talk answered with quantitative claims"})
    return {"passed": not violations, "violations": violations}


def _premise(text: str) -> list:
    lower = text.lower()
    corrected = (any(w in lower for w in _PREMISE_OK)
                 and any(w in lower for w in _PREMISE_CORRECTION))
    if corrected:
        return []
    return [{"type": "premise_not_corrected",
             "detail": "answer does not correct 'Chronos-2 replaced MC'"}]


def score(kind: str, text: str, *, fixture=None, bundle=None, trace=None) -> dict:
    if kind == "none":
        return {"passed": True, "violations": []}
    if kind == "refusal":
        return _refusal(text)
    if kind == "chat":
        return _chat(text)
    if kind == "narration":
        violations = bridge.reflexion_validator.validate(text, fixture)
        return {"passed": not violations, "violations": violations}
    if kind == "triage":
        return bridge.react_oracle_triage.score(text, bundle)
    if kind in ("qa", "qa_premise"):
        result = bridge.react_oracle_drilldown.score(text, bundle, trace)
        violations = list(result["violations"])
        if kind == "qa_premise":
            violations += _premise(text)
        return {"passed": not violations, "violations": violations}
    raise KeyError(kind)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd experiments/hierarchical && python -m pytest tests/test_scoring.py -v`
Expected: 10 PASS.

- [ ] **Step 5: Commit**

```bash
git add experiments/hierarchical
git commit -m "feat(experiments): hierarchical scoring package (routing/state/answers/boundary)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: Session runners + harness + README + live run

**Files:**
- Create: `experiments/hierarchical/runner.py`, `experiments/hierarchical/run_experiment.py`, `experiments/hierarchical/README.md`, `experiments/hierarchical/tests/test_smoke.py`

**Interfaces:**
- Produces: `runner.Seams` (dataclass of injectable LLM touchpoints: `classify(user, summary) -> IntentVerdict`; `clarify(agent, cstate, user) -> dict | None` (returns compiled payload); `answer(agent, prompt) -> str`; `direct(user, summary, route) -> str`; `publish(user, fixture, state) -> Publication`; `respond` (sim-user fake or `None`)); `runner.default_seams(model_id=None) -> Seams`; `runner.run_director_session(session, seams) -> dict`; `runner.run_monolith_session(session, seams) -> dict`. Session results: `{"session", "arm", "turns": [turn records], "wall_clock_s"}`; each turn record has `{"user", "intent", "confidence", "route", "reply", "tool_calls": [names], "publication_channel", "state_after": {"run_status", "has_bundle", "execution_id", "spec_hash"}, "latency_s"}` (monolith records have `intent/route/publication_channel = None`).
- Consumes: everything from Tasks 1–8.

**Runner behavior (Arm B, per turn):** classify → `director.route` → per route:
- `clarifier`: build clarify fixture (`session["clarify"] or specialists.default_clarify_fixture(user)`), fresh `Trace`, `make_clarifier`, `seams.clarify`. Compiled → `sessions.resolve_outcome(turn["resolves_to"])` + `director.apply_outcome`; outcome `complete` → `seams.publish` (reply = publication text, record channel); outcome `failed` → reply = `runner.render_run_failed_notice(state)` (coded status string: run failed, exec id, offer diagnosis — status, not result prose). Not compiled → reply = the clarifier's final text (its question/escalation), state unchanged.
- `qa`/`triage`: fresh `Trace`, `specialists.make_specialist(route, state.bundle, trace)`, `seams.answer(agent, user)`.
- `direct`/`refuse`: `seams.direct(user, state.summary(), route)`. No tools, no state change.

**Runner behavior (Arm A, per turn):** fresh `Trace`, `monolith.make_monolith_agent(clarify_fixture, current_bundle, trace, respond=seams.respond)`, `seams.answer(agent, monolith.build_turn_prompt(transcript, current_bundle, user))`. If the agent compiled (`cstate["compiled"]`) and the turn has `resolves_to`, resolve the same fixture DAG and update `current_bundle` (same environment, no routing help). Transcript grows with every user/assistant pair.

**Harness (`run_experiment.py`):** `--trials N` (default 3), `--sessions` filter, `HIER_MODEL_ID` env. For arm × session × trial: run, then score every turn — `scoring.routing`/`scoring.state` (Arm B only), `scoring.answers.score(turn["score"]["kind"], reply, fixture=active reflexion fixture, bundle=active bundle, trace=None)` (both arms; `trace=None` keeps qa scoring arm-fair on faithfulness — grounding comparison is a react-experiment metric), `scoring.boundary.violations(tool_calls, specialists.ALLOWLISTS[expected_route])` (both arms; Arm B expected 0 by construction). Narration turns score the *published* text. Summary table printed per arm: intent/route/state accuracy, boundary violation count, publication-channel histogram, answer pass-rate by kind, mean latency. Full records + summary to `results/experiment_<unix_ts>.json`.

- [ ] **Step 1: Write the failing test**

`experiments/hierarchical/tests/test_smoke.py` (hermetic — every LLM touchpoint faked):

```python
from types import SimpleNamespace

import director
import runner
import sessions


def _fake_seams():
    def classify(user, summary):
        # Smoke uses ground-truth intents; live runs use the real classifier.
        text_to_intent = {}
        for s in sessions.load_all():
            for t in s["turns"]:
                text_to_intent[t["user"]] = t["expected_intent"]
        return SimpleNamespace(intent=text_to_intent[user], confidence=1.0)

    return runner.Seams(
        classify=classify,
        clarify=lambda agent, cstate, user: {"spec_hash": "fake"},
        answer=lambda agent, prompt: "the run stalled; no numbers to report",
        direct=lambda user, summary, route: "I cannot answer that without a run.",
        publish=lambda user, fixture, state: director.Publication(
            "validated narration", "narrator", 1),
        respond=lambda q: "no preference",
    )


def _session(name):
    return [s for s in sessions.load_all() if s["session"] == name][0]


def test_director_failure_session_routes_and_tracks_state():
    result = runner.run_director_session(_session("s4_midsession_failure"),
                                         _fake_seams())
    routes = [t["route"] for t in result["turns"]]
    assert routes == ["clarifier", "triage", "refuse"]
    statuses = [t["state_after"]["run_status"] for t in result["turns"]]
    assert statuses == ["failed", "failed", "failed"]
    assert result["turns"][0]["publication_channel"] is None  # failed run: no narration


def test_director_clean_session_publishes():
    result = runner.run_director_session(_session("s1_clean_run_drilldown"),
                                         _fake_seams())
    first = result["turns"][0]
    assert first["publication_channel"] == "narrator"
    assert first["reply"] == "validated narration"
    assert result["turns"][2]["route"] == "direct"


def test_monolith_session_runs_and_resolves_bundle():
    result = runner.run_monolith_session(_session("s1_clean_run_drilldown"),
                                         _fake_seams())
    assert len(result["turns"]) == 3
    assert result["turns"][0]["route"] is None
    assert result["turns"][0]["state_after"]["has_bundle"] is True


def test_harness_scores_hermetically(tmp_path):
    import run_experiment
    summary = run_experiment.run_matrix(
        trials=1, seams_factory=lambda model_id: _fake_seams(),
        out_dir=tmp_path, session_filter=["s4_midsession_failure"])
    arms = {row["arm"] for row in summary["by_arm"]}
    assert arms == {"director", "monolith"}
    director_row = [r for r in summary["by_arm"] if r["arm"] == "director"][0]
    assert director_row["route_accuracy"] == 1.0
    assert director_row["boundary_violations"] == 0
    assert list(tmp_path.glob("experiment_*.json"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd experiments/hierarchical && python -m pytest tests/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'runner'`.

- [ ] **Step 3: Write minimal implementation**

`experiments/hierarchical/runner.py`:

```python
"""Per-arm session loops. All LLM touchpoints go through Seams (injectable)."""
import time
from dataclasses import dataclass
from typing import Callable

import bridge
import director
import intents
import monolith
import sessions
import specialists


@dataclass
class Seams:
    classify: Callable
    clarify: Callable
    answer: Callable
    direct: Callable
    publish: Callable
    respond: Callable | None = None


def default_seams(model_id: str | None = None) -> Seams:
    def clarify(agent, cstate, user):
        agent(user)
        return cstate["compiled"]

    return Seams(
        classify=lambda user, summary: intents.classify(user, summary,
                                                        model_id=model_id),
        clarify=clarify,
        answer=lambda agent, prompt: str(agent(prompt)),
        direct=lambda user, summary, route: specialists.direct_reply(
            user, summary, route, model_id=model_id),
        publish=lambda user, fixture, state: director.publish_narration(
            user, fixture, state, model_id=model_id),
        respond=None,
    )


def render_run_failed_notice(state: director.DirectorState) -> str:
    return (f"The run did not complete (status: failed, exec "
            f"{state.execution_id}). No results are available; ask me to "
            "diagnose what went wrong.")


def _state_snapshot(state: director.DirectorState) -> dict:
    return {"run_status": state.run_status,
            "has_bundle": state.bundle is not None,
            "execution_id": state.execution_id,
            "spec_hash": state.spec_hash}


def run_director_session(session: dict, seams: Seams) -> dict:
    state = director.DirectorState()
    records, started = [], time.monotonic()
    for turn in session["turns"]:
        turn_started = time.monotonic()
        trace = bridge.react_trace.Trace()
        verdict = seams.classify(turn["user"], state.summary())
        route = director.route(verdict.intent, state)
        channel = None
        if route == "clarifier":
            fixture = session["clarify"] or specialists.default_clarify_fixture(
                turn["user"])
            agent, cstate = specialists.make_clarifier(
                fixture, trace, respond=seams.respond)
            compiled = seams.clarify(agent, cstate, turn["user"])
            if compiled is None:
                reply = str(cstate.get("final_text") or "Clarification needed.")
            else:
                bundle, nfix, outcome = sessions.resolve_outcome(
                    turn["resolves_to"])
                state = director.apply_outcome(state, bundle, nfix, outcome)
                if outcome == "complete":
                    pub = seams.publish(turn["user"], nfix, state)
                    reply, channel = pub.text, pub.channel
                else:
                    reply = render_run_failed_notice(state)
        elif route in ("qa", "triage"):
            agent = specialists.make_specialist(route, state.bundle, trace)
            reply = seams.answer(agent, turn["user"])
        else:  # direct | refuse — Director prose, no tools
            reply = seams.direct(turn["user"], state.summary(), route)
        records.append({
            "user": turn["user"], "intent": verdict.intent,
            "confidence": getattr(verdict, "confidence", None), "route": route,
            "reply": reply, "tool_calls": trace.tool_names(),
            "publication_channel": channel,
            "state_after": _state_snapshot(state),
            "latency_s": time.monotonic() - turn_started,
        })
    return {"session": session["session"], "arm": "director",
            "turns": records, "wall_clock_s": time.monotonic() - started}


```

Continue `runner.py` with the monolith loop (same file):

```python
def run_monolith_session(session: dict, seams: Seams) -> dict:
    bundle, transcript, run_status = None, [], "none"
    records, started = [], time.monotonic()
    for turn in session["turns"]:
        turn_started = time.monotonic()
        trace = bridge.react_trace.Trace()
        clarify_fixture = session["clarify"] or (
            specialists.default_clarify_fixture(turn["user"]))
        agent, cstate = monolith.make_monolith_agent(
            clarify_fixture, bundle, trace, respond=seams.respond)
        prompt = monolith.build_turn_prompt(transcript, bundle, turn["user"])
        reply = seams.answer(agent, prompt)
        if "resolves_to" in turn and cstate["compiled"] is None:
            # Give the seam a chance to report a compile the stuffed agent
            # made mid-answer (live: cstate already updated by the tool call;
            # smoke: the fake returns a compiled dict).
            cstate["compiled"] = seams.clarify(agent, cstate, turn["user"])
        if "resolves_to" in turn and cstate["compiled"] is not None:
            bundle, _, outcome = sessions.resolve_outcome(turn["resolves_to"])
            run_status = outcome
        records.append({
            "user": turn["user"], "intent": None, "confidence": None,
            "route": None, "reply": reply, "tool_calls": trace.tool_names(),
            "publication_channel": None,
            "state_after": {"run_status": run_status,
                            "has_bundle": bundle is not None,
                            "execution_id": (bundle or {}).get(
                                "run_spec", {}).get("execution_id"),
                            "spec_hash": (bundle or {}).get(
                                "run_spec", {}).get("spec_hash")},
            "latency_s": time.monotonic() - turn_started,
        })
        transcript += [{"role": "user", "text": turn["user"]},
                       {"role": "assistant", "text": reply}]
    return {"session": session["session"], "arm": "monolith",
            "turns": records, "wall_clock_s": time.monotonic() - started}
```

One caveat baked in above: live Arm A calls `seams.clarify(agent, cstate, ...)` only when the agent did not already compile during its answer — and `default_seams.clarify` re-invokes the agent. To avoid double-invoking live, `run_experiment.py` builds Arm A seams with `clarify=lambda agent, cstate, user: cstate["compiled"]` (report-only). The smoke test's fake returns a compiled dict, which is exactly the injection point the test needs.

Note the clarifier's not-compiled reply: react's `state` dict has no `final_text` key by default — the runner falls back to `"Clarification needed."`. If the implemented react `make_clarify_tools` state exposes the agent's last text under a different key, use that instead (adapt here only).

`experiments/hierarchical/run_experiment.py`:

```python
"""Harness: arms x sessions x trials, scored per turn, results to JSON."""
import argparse
import json
import pathlib
import time

import runner
import sessions
import specialists
from scoring import answers, boundary, routing, state as state_scoring


def _score_director_turn(turn, record):
    return {
        "routing": routing.score_turn(record["intent"], record["route"], turn),
        "state": state_scoring.score_state(
            _StateView(record["state_after"]), turn["expected_state_after"]),
        "answer": _answer_score(turn, record),
        "boundary": boundary.violations(
            [{"name": n} for n in record["tool_calls"]],
            specialists.ALLOWLISTS[turn["expected_route"]]),
    }


class _StateView:
    def __init__(self, snapshot):
        self.run_status = snapshot["run_status"]
        self.bundle = object() if snapshot["has_bundle"] else None


def _answer_score(turn, record):
    kind = turn["score"]["kind"]
    fixture = record.get("_fixture")
    bundle = record.get("_bundle")
    return answers.score(kind, record["reply"], fixture=fixture, bundle=bundle)


def _attach_evidence(session, records):
    """Give each record the active fixture/bundle its score kind needs."""
    fixture = bundle = None
    for turn, record in zip(session["turns"], records):
        if "resolves_to" in turn:
            b, f, _ = sessions.resolve_outcome(turn["resolves_to"])
            bundle, fixture = b, f
        record["_bundle"], record["_fixture"] = bundle, fixture


def _score_monolith_turn(turn, record):
    return {
        "routing": None, "state": None,
        "answer": _answer_score(turn, record),
        "boundary": boundary.violations(
            [{"name": n} for n in record["tool_calls"]],
            specialists.ALLOWLISTS[turn["expected_route"]]),
    }


def run_matrix(trials: int, seams_factory, out_dir, session_filter=None,
               model_id=None):
    out_dir = pathlib.Path(out_dir)
    all_sessions = [s for s in sessions.load_all()
                    if not session_filter or s["session"] in session_filter]
    results = []
    for arm, run_fn, scorer in (
            ("director", runner.run_director_session, _score_director_turn),
            ("monolith", runner.run_monolith_session, _score_monolith_turn)):
        for session in all_sessions:
            for trial in range(trials):
                seams = seams_factory(model_id)
                if arm == "monolith" and seams.respond is None:
                    # Live Arm A: report-only — the stuffed agent compiles (or
                    # not) via its own tool calls; never re-invoke it. Fake
                    # seams (respond set) keep their injected clarify.
                    seams.clarify = lambda agent, cstate, user: cstate["compiled"]
                result = run_fn(session, seams)
                _attach_evidence(session, result["turns"])
                for turn, record in zip(session["turns"], result["turns"]):
                    record["scores"] = scorer(turn, record)
                    record.pop("_bundle", None)
                    record.pop("_fixture", None)
                result["trial"] = trial
                results.append(result)
    summary = _summarize(results)
    out_path = out_dir / f"experiment_{int(time.time())}.json"
    out_path.write_text(json.dumps({"summary": summary, "results": results},
                                   indent=2, default=str))
    _print_table(summary)
    return summary
```

```python
def _summarize(results: list) -> dict:
    by_arm = []
    for arm in ("director", "monolith"):
        rows = [t for r in results if r["arm"] == arm for t in r["turns"]]
        n = len(rows)
        routed = [t for t in rows if t["scores"]["routing"]]
        by_arm.append({
            "arm": arm, "turns": n,
            "intent_accuracy": (sum(t["scores"]["routing"]["intent_correct"]
                                    for t in routed) / len(routed)) if routed else None,
            "route_accuracy": (sum(t["scores"]["routing"]["route_correct"]
                                   for t in routed) / len(routed)) if routed else None,
            "state_accuracy": (sum(t["scores"]["state"]["passed"]
                                   for t in routed) / len(routed)) if routed else None,
            "boundary_violations": sum(len(t["scores"]["boundary"]) for t in rows),
            "answer_pass_rate": sum(t["scores"]["answer"]["passed"]
                                    for t in rows) / n if n else None,
            "publication_channels": _histogram(
                t["publication_channel"] for t in rows),
            "mean_latency_s": sum(t["latency_s"] for t in rows) / n if n else None,
        })
    return {"by_arm": by_arm}


def _histogram(values) -> dict:
    counts = {}
    for v in values:
        if v is not None:
            counts[v] = counts.get(v, 0) + 1
    return counts


def _print_table(summary: dict) -> None:
    cols = ("arm", "turns", "intent_accuracy", "route_accuracy",
            "state_accuracy", "boundary_violations", "answer_pass_rate",
            "publication_channels", "mean_latency_s")
    for row in summary["by_arm"]:
        print(" | ".join(f"{c}={row[c]}" for c in cols))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--sessions", nargs="*", default=None)
    parser.add_argument("--model-id", default=None)
    args = parser.parse_args()
    run_matrix(args.trials, runner_default_factory, "results",
               session_filter=args.sessions, model_id=args.model_id)


def runner_default_factory(model_id):
    return runner.default_seams(model_id)


if __name__ == "__main__":
    main()
```

`experiments/hierarchical/README.md` — write it covering: what the experiment measures (spec §1's four properties), prerequisite (react built), how to run (`python -m pytest tests/ -v`, then `python run_experiment.py --trials 3`), how to read the summary table (route/state accuracy and boundary violations are Arm-B diagnostics; answer pass-rate, publication channels, and boundary counts are the cross-arm comparison; `table_error > 0` means a route-table bug, not a model failure), and cost expectations (spec §11).

- [ ] **Step 4: Run tests to verify they pass (full hermetic suite)**

Run: `cd experiments/hierarchical && python -m pytest tests/ -v`
Expected: all PASS across all 9 test files.
Also run: `cd /Users/muffadal/code/chronos-2-demo && pytest -q`
Expected: root suite green and unchanged.

- [ ] **Step 5: Commit**

```bash
git add experiments/hierarchical
git commit -m "feat(experiments): hierarchical session runners + A/B harness + README

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Live run (the only networked step)**

Run from `experiments/hierarchical/` with AWS credentials for the account (Bedrock, us-east-1):

```bash
python run_experiment.py --trials 3
```

Expected: 48 session runs (2 arms × 8 sessions × 3 trials); a `results/experiment_*.json` with per-turn records and the printed two-row summary table. Inspect: Arm B `boundary_violations` MUST be 0; `table_error` count MUST be 0; compare `answer_pass_rate` and `publication_channels` across arms. Do not commit `results/` (gitignored). Record headline numbers in the task summary for the user.

---

## Execution notes

- **Prerequisite ordering is enforced by Task 1** — if `experiments/react/` is missing or its interfaces drifted, `test_bridge.py` fails and the run stops there. Fix by implementing the react plan first, not by stubbing the bridge.
- **Interface drift policy:** exact react signatures come from its plan; if the implemented code differs, adapt `bridge.py`/`specialists.py`/`runner.py` call sites only, keep this plan's tests' *behavioral* assertions, and log the deviation in the task summary.
- Root `pyproject.toml` `testpaths=["tests"]` already excludes `experiments/`; verify once in Task 1, never edit.
- **Cost accounting is best-effort:** per-turn wall-clock latency and tool-call counts are always recorded; publication attempts carry token counts (reflexion `Generation`). Per-agent-invocation tokens are recorded only if the installed Strands result exposes usage (check how react's harness reads it and mirror that) — do not build custom token plumbing.
- **`trace` stdlib collision:** `bridge.py` loads react's top-level modules by file path because `trace` is a Python stdlib module name. If a react module *internally* does `import trace` (check `tools.py`/`clarify_tools.py` when implementing), it will get the stdlib module when imported from here — in that case set `sys.modules["react_internal_trace_guard"]` aside and instead load that react module by file path too, after `sys.modules` temporarily maps `"trace"` to `react_trace` during its exec. Only do this if the plain load actually fails; note it in the task summary.






