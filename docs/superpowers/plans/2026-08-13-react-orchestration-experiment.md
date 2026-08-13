# ReAct Orchestration Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the local-only `experiments/react/` harness that measures whether a bounded ReAct layer around the deterministic quant core improves pre-run clarification, post-failure triage, and post-success drilldown versus current static behaviors (spec: `docs/superpowers/specs/2026-08-13-react-orchestration-experiment-design.md`).

**Architecture:** Reflexion fixtures are converted into evidence *bundles* (run_spec + synthesized event stream + artifact manifest + exposure + diagnostics). Three roles run as A/B arms: Arm A replicates today's static behavior (direct `compile_run_spec`, tool-less stuffed prompts); Arm B is a Strands agent with role-scoped tools (clarification: defaults/ask_user/compile_spec with an LLM simulated user; triage/drilldown: read-only evidence tools). Deterministic per-role oracles score both arms; a harness runs the 3 roles × 2 arms × scenarios × N trials matrix.

**Tech Stack:** Python 3.11, `strands-agents==1.30.0` (Bedrock), pytest. Model: `us.anthropic.claude-opus-5` (no `temperature`/`top_p`/`top_k` — removed on Opus 5; thinking on by default), env-overridable.

**Spec:** `docs/superpowers/specs/2026-08-13-react-orchestration-experiment-design.md`

## Global Constraints

- Everything lives under `experiments/react/`. Do NOT modify `src/`, `agent/`, `tools/`, `infra/`, `frontend/`, `pyproject.toml`, root `tests/`, or anything under `experiments/reflexion/` (read-only reuse).
- Root `pytest` must stay green and must NOT collect experiment tests (`pyproject.toml` sets `testpaths=["tests"]` — verify, don't edit).
- Experiment unit tests are hermetic: no network, no Bedrock, no S3. Only the final harness run (Task 9, last step) touches Bedrock.
- Model ID from env `REACT_MODEL_ID`, default `us.anthropic.claude-opus-5`. Never pass sampling params. `BedrockModel(model_id=..., max_tokens=8192)` only.
- Reflexion reuse is by path, read-only: fixtures from `experiments/reflexion/fixtures/*.json`; `validator.py` imported via a `sys.path` bridge (`experiments/reflexion` appended). Never copy or edit reflexion files.
- The quant DAG never executes. No tool in this experiment runs, reruns, or mutates anything — evidence tools are pure reads over an in-memory bundle dict.
- `compile_run_spec` is the real one: `from chronos2_demo.run_spec import compile_run_spec, canonical_run_payload, Clarification, PROFILE` (package is installed editable in `.venv`).
- Dummy provenance for all compiles (spec hash comparability depends on every compile using this exact dict): the 14 keys from `agent/runtime/agent.py` `PROVENANCE_ENV`, each mapped to the string `"experiment"`.
- Run everything from `experiments/react/` (relative `fixtures/` paths, mirroring the reflexion convention). Tests run as `python -m pytest tests/ -v` from `experiments/react/`.
- One commit per task, message as written in the task, ending with the trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## File Structure

```
experiments/react/
├── requirements.txt          # strands-agents==1.30.0 (same pin as reflexion)
├── README.md                 # how to run + how to read results (Task 9)
├── bundle.py                 # reflexion fixture → evidence bundle (Task 1)
├── mutate.py                 # 5 triage mutations → committed fixtures (Task 2)
├── oracles/
│   ├── __init__.py
│   ├── clarify.py            # clarification oracle (Task 3)
│   ├── triage.py             # triage oracle (Task 6)
│   └── drilldown.py          # drilldown oracle, imports reflexion validator (Task 7)
├── trace.py                  # tool-call trace recorder (Task 4)
├── tools.py                  # read-only evidence tools factory (Task 4)
├── sim_user.py               # hidden-intent simulated user (Task 5)
├── clarify_tools.py          # get_approved_defaults / ask_user / compile_spec (Task 5)
├── agents.py                 # 6 arm functions + system prompts (Task 8)
├── scenarios.py              # role → scenario matrix (Task 9)
├── run_experiment.py         # harness: roles × arms × scenarios × trials (Task 9)
├── fixtures/
│   ├── drilldown_happy.json        # bundle of reflexion happy_path (Task 1)
│   ├── drilldown_conditional.json  # bundle of reflexion conditional_whatif (Task 1)
│   ├── triage_missing_exposure.json  # (Task 2)
│   ├── triage_id_mismatch.json       # (Task 2)
│   ├── triage_partial_events.json    # (Task 2)
│   ├── triage_poll_timeout.json      # (Task 2)
│   ├── triage_hash_mismatch.json     # (Task 2)
│   └── clarify/                      # 6 scenario JSONs (Task 3)
├── results/                  # gitignored output (metrics + transcripts)
└── tests/
    ├── __init__.py
    ├── test_bundle.py
    ├── test_mutate.py
    ├── test_oracle_clarify.py
    ├── test_tools_trace.py
    ├── test_clarify_tools.py
    ├── test_oracle_triage.py
    ├── test_oracle_drilldown.py
    └── test_smoke.py         # agents/harness import + prompt-shape smoke (no network)
```

**Bundle schema** (produced by Task 1/2, consumed by tools, arms, oracles):

```json
{
  "defect": null,
  "expected_posture": "full",
  "ground_truth": null,
  "run_spec": {"...": "reflexion workflow.run_spec verbatim (incl. spec_hash, execution_id)"},
  "events": [{"seq": 0, "type": "tool", "name": "load_data", "status": "done"}],
  "artifact_manifest": [{"uri": "s3://...", "sha256": "...", "kind": "metrics", "scenario_role": "baseline"}],
  "task_status": {"baseline_mc": "STOPPED", "chronos2": "STOPPED"},
  "exposure": {"baseline": {"...": "reflexion exposure payload + injected metrics_sha256"}},
  "diagnostics": {"...": "reflexion workflow.diagnostics verbatim"}
}
```

Degraded bundles set `expected_posture: "degraded"`, `defect: <name>`, and `ground_truth: {"failed_step": "...", "defect": "...", "keywords": ["..."]}`. Captured exposure payloads carry `paths_sha256` + `metrics_uri` but **no** `metrics_sha256`; `bundle.py` injects a deterministic one (sha256 of the payload's canonical JSON) into both the exposure payload and its manifest entry so integrity comparisons are self-consistent — `hash_mismatch` then corrupts only the manifest copy.

**Clarification scenario schema** (Task 3):

```json
{
  "scenario": "vague_stress",
  "prompt": "Run a stress scenario",
  "expected_posture": "compile",
  "hidden_intent": {"w_stress": 0.75},
  "known_fields": ["w_stress", "as_of_date"],
  "must_resolve": ["w_stress"],
  "max_questions_ok": 1
}
```

`expected_posture` ∈ {`compile`, `correct_premise`}. `hidden_intent` holds only fields the intent fixes to **non-default** values; every other required field is expected to equal `PROFILE` defaults in the compiled payload. `known_fields` is what the sim user can answer concretely. `must_resolve` are intent fields not derivable from the prompt (a compile with the wrong value there is `guessed_while_blocked`). `max_questions_ok` bounds `asked_while_not_blocked`.

---

### Task 1: Scaffolding + bundle builder + drilldown bundles

**Files:**
- Create: `experiments/react/requirements.txt`, `experiments/react/bundle.py`, `experiments/react/tests/__init__.py`, `experiments/react/tests/test_bundle.py`, `experiments/react/results/.gitkeep`, `experiments/react/oracles/__init__.py`, `experiments/react/fixtures/drilldown_happy.json` (generated), `experiments/react/fixtures/drilldown_conditional.json` (generated)
- Modify: `.gitignore` (append `experiments/react/results/*` and `!experiments/react/results/.gitkeep`)

**Interfaces:**
- Produces: `bundle.build_bundle(fixture: dict) -> dict` (bundle schema above); `bundle.synthesize_events(workflow: dict) -> list[dict]`; `bundle.payload_sha256(payload: dict) -> str`; CLI `python bundle.py` writes the two drilldown fixtures from the reflexion captures.
- Consumes: `experiments/reflexion/fixtures/{happy_path,conditional_whatif}.json` (read-only).

- [ ] **Step 1: Write requirements + verify env**

`experiments/react/requirements.txt`:
```
strands-agents==1.30.0
```

Run: `source .venv/bin/activate && pip install -r experiments/react/requirements.txt && python -c "from strands import Agent, tool; print('ok')"`
Expected: `ok` (already satisfied — reflexion installed the same pin).

- [ ] **Step 2: Write the failing test**

`experiments/react/tests/__init__.py`: empty file.

`experiments/react/tests/test_bundle.py`:
```python
import json
import pathlib

import bundle

_REFLEXION_FIXTURES = (
    pathlib.Path(__file__).resolve().parents[2] / "reflexion" / "fixtures"
)


def _mini_fixture() -> dict:
    payload = lambda role, source: {
        "execution_id": "e" * 32, "spec_hash": "a" * 64,
        "scenario_role": role, "source": source,
        "metrics_uri": f"s3://b/runs/{'e'*32}/metrics/{role}.json",
        "paths_uri": f"s3://b/runs/{'e'*32}/paths/{role}.parquet",
        "paths_sha256": "b" * 64,
        "ee": [1.0], "pfe_975": [2.0], "es_975": [3.0], "dates": ["2023-09-19"],
        "terminal": {"date": "2023-09-19", "ee": 1.0, "pfe_975": 2.0, "es_975": 3.0},
    }
    return {
        "defect": None, "expected_posture": "full", "scenario_hint": "happy_path",
        "workflow": {
            "run_spec": {"execution_id": "e" * 32, "spec_hash": "a" * 64,
                         "as_of_date": "2022-09-30", "conditioning": None},
            "exposure": {
                "baseline": payload("baseline", "parametric"),
                "chronos_only": payload("chronos_only", "chronos2"),
                "augmented": payload("augmented", "blended"),
            },
            "diagnostics": {"execution_id": "e" * 32},
        },
    }


def test_build_bundle_shape():
    b = bundle.build_bundle(_mini_fixture())
    assert b["expected_posture"] == "full" and b["defect"] is None
    assert b["run_spec"]["as_of_date"] == "2022-09-30"
    assert set(b["exposure"]) == {"baseline", "chronos_only", "augmented"}
    assert b["diagnostics"] == {"execution_id": "e" * 32}
    assert b["task_status"] == {"baseline_mc": "STOPPED", "chronos2": "STOPPED"}


def test_synthesized_events_cover_canonical_dag_in_order():
    b = bundle.build_bundle(_mini_fixture())
    names = [(e["name"], e.get("scenario_role") or e.get("plot_role")) for e in b["events"]]
    assert names == [
        ("load_data", None), ("plot", "regime_ribbon"),
        ("run_baseline_mc", None), ("run_chronos2", None),
        ("check_baseline_mc", None), ("check_chronos2", None),
        ("blend_paths", None),
        ("price_book", "baseline"), ("price_book", "chronos_only"),
        ("price_book", "augmented"), ("plot", "pfe_overlay"),
    ]
    assert [e["seq"] for e in b["events"]] == list(range(11))
    assert all(e["status"] == "done" for e in b["events"])
    checks = [e for e in b["events"] if e["name"].startswith("check_")]
    assert all(e["ready"] is True and e["task_status"] == "STOPPED" for e in checks)


def test_metrics_sha_injected_and_mirrored_in_manifest():
    b = bundle.build_bundle(_mini_fixture())
    by_role = {m["scenario_role"]: m for m in b["artifact_manifest"] if m["kind"] == "metrics"}
    assert set(by_role) == {"baseline", "chronos_only", "augmented"}
    for role, entry in by_role.items():
        assert entry["sha256"] == b["exposure"][role]["metrics_sha256"]
        assert entry["uri"] == b["exposure"][role]["metrics_uri"]
    paths = [m for m in b["artifact_manifest"] if m["kind"] == "paths"]
    assert {m["scenario_role"] for m in paths} == {"baseline", "chronos_only", "augmented"}
    assert all(m["sha256"] == "b" * 64 for m in paths)


def test_sha_deterministic_and_input_not_mutated():
    fx = _mini_fixture()
    before = json.dumps(fx, sort_keys=True)
    b1, b2 = bundle.build_bundle(fx), bundle.build_bundle(fx)
    assert json.dumps(fx, sort_keys=True) == before
    assert (b1["exposure"]["baseline"]["metrics_sha256"]
            == b2["exposure"]["baseline"]["metrics_sha256"])


def test_real_reflexion_fixtures_bundle():
    for name in ("happy_path", "conditional_whatif"):
        fx = json.loads((_REFLEXION_FIXTURES / f"{name}.json").read_text())
        b = bundle.build_bundle(fx)
        assert len(b["events"]) == 11 and b["diagnostics"] is not None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd experiments/react && python -m pytest tests/test_bundle.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bundle'`.

- [ ] **Step 4: Write `bundle.py`**

```python
"""Convert reflexion narration fixtures into react evidence bundles (spec §5)."""
import argparse
import copy
import hashlib
import json
import pathlib

REFLEXION_FIXTURES = (
    pathlib.Path(__file__).resolve().parents[1] / "reflexion" / "fixtures"
)
ROLES = ("baseline", "chronos_only", "augmented")


def payload_sha256(payload: dict) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def synthesize_events(workflow: dict) -> list[dict]:
    events: list[dict] = []

    def add(name: str, **extra) -> None:
        events.append({"seq": len(events), "type": "tool", "name": name,
                       "status": "done", **extra})

    add("load_data")
    add("plot", plot_role="regime_ribbon")
    add("run_baseline_mc")
    add("run_chronos2")
    add("check_baseline_mc", ready=True, task_status="STOPPED")
    add("check_chronos2", ready=True, task_status="STOPPED")
    add("blend_paths")
    for role in ROLES:
        payload = workflow.get("exposure", {}).get(role)
        if payload is not None:
            add("price_book", scenario_role=role,
                source=payload.get("source"), terminal=payload.get("terminal"))
    add("plot", plot_role="pfe_overlay")
    return events


def build_bundle(fixture: dict) -> dict:
    workflow = copy.deepcopy(fixture["workflow"])
    manifest = []
    for role in ROLES:
        payload = workflow.get("exposure", {}).get(role)
        if payload is None:
            continue
        payload["metrics_sha256"] = payload_sha256(payload)
        manifest.append({"uri": payload["metrics_uri"],
                         "sha256": payload["metrics_sha256"],
                         "kind": "metrics", "scenario_role": role})
        manifest.append({"uri": payload["paths_uri"],
                         "sha256": payload["paths_sha256"],
                         "kind": "paths", "scenario_role": role})
    return {
        "defect": fixture.get("defect"),
        "expected_posture": fixture.get("expected_posture", "full"),
        "ground_truth": None,
        "run_spec": workflow["run_spec"],
        "events": synthesize_events(workflow),
        "artifact_manifest": manifest,
        "task_status": {"baseline_mc": "STOPPED", "chronos2": "STOPPED"},
        "exposure": workflow.get("exposure", {}),
        "diagnostics": workflow.get("diagnostics"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="fixtures")
    args = parser.parse_args()
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for source, target in (("happy_path", "drilldown_happy"),
                           ("conditional_whatif", "drilldown_conditional")):
        fixture = json.loads((REFLEXION_FIXTURES / f"{source}.json").read_text())
        path = out_dir / f"{target}.json"
        path.write_text(json.dumps(build_bundle(fixture), sort_keys=True,
                                   indent=2, allow_nan=False) + "\n")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd experiments/react && python -m pytest tests/test_bundle.py -v`
Expected: 5 PASS.

- [ ] **Step 6: Generate drilldown fixtures, gitignore results, verify root suite untouched**

Run from `experiments/react/`: `mkdir -p results oracles && touch results/.gitkeep oracles/__init__.py && python bundle.py`
Expected: `wrote fixtures/drilldown_happy.json`, `wrote fixtures/drilldown_conditional.json`.

Append to root `.gitignore`:
```
experiments/react/results/*
!experiments/react/results/.gitkeep
```

Run from repo root: `python -m pytest --collect-only -q | tail -3`
Expected: same collection count as before this task (no `experiments/` tests collected).

- [ ] **Step 7: Commit**

```bash
git add experiments/react .gitignore
git commit -m "feat(experiments): react scaffolding + evidence bundle builder

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 2: Triage mutations + committed triage fixtures

**Files:**
- Create: `experiments/react/mutate.py`, `experiments/react/tests/test_mutate.py`, `experiments/react/fixtures/triage_{missing_exposure,id_mismatch,partial_events,poll_timeout,hash_mismatch}.json` (generated)

**Interfaces:**
- Consumes: `bundle.build_bundle`, `bundle.REFLEXION_FIXTURES`.
- Produces: `mutate.MUTATIONS: dict[str, Callable[[dict], dict]]` — each takes a **full bundle** and returns a degraded bundle with `ground_truth = {"failed_step": str, "defect": str, "keywords": list[str]}`; CLI `python mutate.py` writes the 5 fixtures.

- [ ] **Step 1: Write the failing test**

`experiments/react/tests/test_mutate.py`:
```python
import json

import bundle
import mutate
from tests.test_bundle import _mini_fixture


def _base() -> dict:
    return bundle.build_bundle(_mini_fixture())


def test_all_five_mutations_registered():
    assert set(mutate.MUTATIONS) == {
        "missing_exposure", "id_mismatch", "partial_events",
        "poll_timeout", "hash_mismatch",
    }


def test_every_mutation_sets_degraded_posture_and_ground_truth():
    for name, fn in mutate.MUTATIONS.items():
        out = fn(_base())
        assert out["expected_posture"] == "degraded" and out["defect"] == name
        gt = out["ground_truth"]
        assert gt["defect"] == name and gt["failed_step"] and gt["keywords"]


def test_missing_exposure_drops_chronos_only_everywhere():
    out = mutate.MUTATIONS["missing_exposure"](_base())
    assert "chronos_only" not in out["exposure"]
    assert not [e for e in out["events"]
                if e.get("scenario_role") == "chronos_only"]
    assert not [m for m in out["artifact_manifest"]
                if m["scenario_role"] == "chronos_only"]
    assert out["ground_truth"]["failed_step"] == "price_book"


def test_id_mismatch_corrupts_augmented_spec_hash_only():
    base = _base()
    original = base["exposure"]["augmented"]["spec_hash"]
    out = mutate.MUTATIONS["id_mismatch"](base)
    corrupted = out["exposure"]["augmented"]["spec_hash"]
    assert corrupted != original and corrupted.startswith("deadbeef")
    assert out["exposure"]["baseline"]["spec_hash"] == original
    assert out["run_spec"]["spec_hash"] == original


def test_partial_events_truncates_after_check_chronos2():
    out = mutate.MUTATIONS["partial_events"](_base())
    names = [e["name"] for e in out["events"]]
    assert names[-1] == "malformed" and "blend_paths" not in names
    assert out["events"][-1]["raw"].startswith('{"seq"')
    assert out["exposure"] == {} and out["diagnostics"] is None
    assert out["ground_truth"]["failed_step"] == "blend_paths"


def test_poll_timeout_leaves_chronos_running_with_no_downstream():
    out = mutate.MUTATIONS["poll_timeout"](_base())
    assert out["task_status"]["chronos2"] == "RUNNING"
    last = out["events"][-1]
    assert last["name"] == "check_chronos2" and last["status"] == "failed"
    assert "poll attempt limit exhausted" in last["message"]
    polls = [e for e in out["events"]
             if e["name"] == "check_chronos2" and e["status"] == "done"]
    assert len(polls) == 3 and all(e["ready"] is False for e in polls)
    assert set(out["exposure"]) == set()
    assert "blend_paths" not in [e["name"] for e in out["events"]]
    assert out["ground_truth"]["failed_step"] == "check_chronos2"


def test_hash_mismatch_diverges_manifest_from_exposure():
    out = mutate.MUTATIONS["hash_mismatch"](_base())
    entry = next(m for m in out["artifact_manifest"]
                 if m["kind"] == "metrics" and m["scenario_role"] == "augmented")
    assert entry["sha256"] != out["exposure"]["augmented"]["metrics_sha256"]
    assert entry["sha256"].startswith("deadbeef")


def test_mutations_do_not_share_state():
    base = _base()
    snapshot = json.dumps(base, sort_keys=True)
    for fn in mutate.MUTATIONS.values():
        fn(base)
    assert json.dumps(base, sort_keys=True) == snapshot
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd experiments/react && python -m pytest tests/test_mutate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mutate'`.

- [ ] **Step 3: Write `mutate.py`**

```python
"""Deterministic bundle-level degradations for the triage role (spec §5)."""
import argparse
import copy
import json
import pathlib

import bundle as bundle_mod

GROUND_TRUTH = {
    "missing_exposure": {
        "failed_step": "price_book",
        "keywords": ["missing", "chronos_only", "chronos-only", "absent",
                     "no exposure", "two of three", "incomplete"],
    },
    "id_mismatch": {
        "failed_step": "price_book",
        "keywords": ["spec_hash", "mismatch", "inconsistent", "provenance",
                     "deadbeef", "augmented"],
    },
    "partial_events": {
        "failed_step": "blend_paths",
        "keywords": ["truncated", "malformed", "incomplete", "unparseable",
                     "partial", "cut off", "blend"],
    },
    "poll_timeout": {
        "failed_step": "check_chronos2",
        "keywords": ["timeout", "timed out", "poll", "still running",
                     "running", "exhausted", "chronos"],
    },
    "hash_mismatch": {
        "failed_step": "artifact_integrity",
        "keywords": ["sha256", "hash", "mismatch", "integrity", "manifest",
                     "augmented", "disagree"],
    },
}


def _degraded(source: dict, defect: str) -> dict:
    out = copy.deepcopy(source)
    out["expected_posture"] = "degraded"
    out["defect"] = defect
    out["ground_truth"] = {"defect": defect, **GROUND_TRUTH[defect]}
    return out


def missing_exposure(source: dict) -> dict:
    out = _degraded(source, "missing_exposure")
    del out["exposure"]["chronos_only"]
    out["events"] = [e for e in out["events"]
                     if e.get("scenario_role") != "chronos_only"]
    for seq, event in enumerate(out["events"]):
        event["seq"] = seq
    out["artifact_manifest"] = [m for m in out["artifact_manifest"]
                                if m["scenario_role"] != "chronos_only"]
    return out


def id_mismatch(source: dict) -> dict:
    out = _degraded(source, "id_mismatch")
    augmented = out["exposure"]["augmented"]
    augmented["spec_hash"] = "deadbeef" + augmented["spec_hash"][8:]
    return out


def partial_events(source: dict) -> dict:
    out = _degraded(source, "partial_events")
    cut = next(i for i, e in enumerate(out["events"])
               if e["name"] == "blend_paths")
    dropped = out["events"][cut]
    raw = json.dumps(dropped, sort_keys=True)
    out["events"] = out["events"][:cut] + [{
        "seq": cut, "type": "malformed", "name": "malformed",
        "status": "unknown", "raw": raw[: len(raw) // 2],
    }]
    out["exposure"] = {}
    out["diagnostics"] = None
    out["artifact_manifest"] = [m for m in out["artifact_manifest"]
                                if m["kind"] == "paths"]
    return out


def poll_timeout(source: dict) -> dict:
    out = _degraded(source, "poll_timeout")
    out["task_status"]["chronos2"] = "RUNNING"
    out["exposure"] = {}
    out["diagnostics"] = None
    out["artifact_manifest"] = [
        m for m in out["artifact_manifest"]
        if m["kind"] == "paths" and m["scenario_role"] == "baseline"
    ]
    kept = [e for e in out["events"] if e["name"] in
            ("load_data", "plot", "run_baseline_mc", "run_chronos2",
             "check_baseline_mc") and e.get("plot_role") != "pfe_overlay"]
    for attempt in range(3):
        kept.append({"seq": 0, "type": "tool", "name": "check_chronos2",
                     "status": "done", "ready": False,
                     "task_status": "RUNNING", "attempt": attempt + 1})
    kept.append({"seq": 0, "type": "tool", "name": "check_chronos2",
                 "status": "failed",
                 "message": "check_chronos2 failed: poll attempt limit "
                            "exhausted; latest task_status=RUNNING"})
    for seq, event in enumerate(kept):
        event["seq"] = seq
    out["events"] = kept
    return out


def hash_mismatch(source: dict) -> dict:
    out = _degraded(source, "hash_mismatch")
    entry = next(m for m in out["artifact_manifest"]
                 if m["kind"] == "metrics" and m["scenario_role"] == "augmented")
    entry["sha256"] = "deadbeef" + entry["sha256"][8:]
    return out


MUTATIONS = {
    "missing_exposure": missing_exposure,
    "id_mismatch": id_mismatch,
    "partial_events": partial_events,
    "poll_timeout": poll_timeout,
    "hash_mismatch": hash_mismatch,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="fixtures")
    args = parser.parse_args()
    source = json.loads(
        (bundle_mod.REFLEXION_FIXTURES / "happy_path.json").read_text()
    )
    base = bundle_mod.build_bundle(source)
    out_dir = pathlib.Path(args.out_dir)
    for name, fn in MUTATIONS.items():
        path = out_dir / f"triage_{name}.json"
        path.write_text(json.dumps(fn(base), sort_keys=True, indent=2,
                                   allow_nan=False) + "\n")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd experiments/react && python -m pytest tests/test_mutate.py tests/test_bundle.py -v`
Expected: all PASS.

- [ ] **Step 5: Generate + commit**

Run from `experiments/react/`: `python mutate.py`
Expected: 5 `wrote fixtures/triage_*.json` lines.

```bash
git add experiments/react
git commit -m "feat(experiments): react triage mutations + degraded bundle fixtures

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 3: Clarification scenarios + clarification oracle

**Files:**
- Create: `experiments/react/fixtures/clarify/{fully_specified,one_field_missing,vague_stress,hopelessly_vague,whatif_conditioning,misleading_premise}.json`, `experiments/react/oracles/clarify.py`, `experiments/react/tests/test_oracle_clarify.py`

**Interfaces:**
- Consumes: `chronos2_demo.run_spec.PROFILE`.
- Produces: `oracles.clarify.score(outcome: dict, fixture: dict) -> dict` where `outcome = {"compiled": dict | None, "questions": list[str], "final_text": str}` (compiled = canonical payload incl. `spec_hash`) and the return is `{"passed": bool, "violations": [{"type", "detail"}], "questions_asked": int}`. Violation types: `unresolved`, `wrong_field`, `guessed_while_blocked`, `default_drift`, `asked_while_not_blocked`, `premise_not_corrected`, `compiled_false_premise_only`.
- Scenario fixtures follow the clarification schema in the File Structure section; Task 8's Arm functions produce `outcome` dicts in exactly this shape.

- [ ] **Step 1: Write the six scenario fixtures**

`experiments/react/fixtures/clarify/fully_specified.json`:
```json
{
  "scenario": "fully_specified",
  "prompt": "Run the stage-safe headline demo as of 2022-09-30.",
  "expected_posture": "compile",
  "hidden_intent": {},
  "known_fields": [],
  "must_resolve": [],
  "max_questions_ok": 0
}
```

`experiments/react/fixtures/clarify/one_field_missing.json` (the prompt's date is not machine-parseable; Arm A silently compiles the profile default `2022-09-30` — the wrong date):
```json
{
  "scenario": "one_field_missing",
  "prompt": "Run the stage-safe headline demo, but as of the worst point of the COVID crash.",
  "expected_posture": "compile",
  "hidden_intent": {"as_of_date": "2020-03-31"},
  "known_fields": ["as_of_date"],
  "must_resolve": ["as_of_date"],
  "max_questions_ok": 1
}
```

`experiments/react/fixtures/clarify/vague_stress.json` (no profile keyword, so Arm A gets `Please specify: ...` and ends unresolved):
```json
{
  "scenario": "vague_stress",
  "prompt": "Run a stress scenario on the book.",
  "expected_posture": "compile",
  "hidden_intent": {"w_stress": 0.75},
  "known_fields": ["w_stress"],
  "must_resolve": ["w_stress"],
  "max_questions_ok": 2
}
```

`experiments/react/fixtures/clarify/hopelessly_vague.json` (no action verb — Arm A classifies as non-quantitative):
```json
{
  "scenario": "hopelessly_vague",
  "prompt": "so, can you give me the numbers?",
  "expected_posture": "compile",
  "hidden_intent": {},
  "known_fields": [],
  "must_resolve": [],
  "max_questions_ok": 1
}
```

`experiments/react/fixtures/clarify/whatif_conditioning.json` (fully machine-parseable; both arms should compile identically):
```json
{
  "scenario": "whatif_conditioning",
  "prompt": "What happens if EUR rates fall 50 basis points for the first 10 business days across two and five year tenors? Use the stage-safe setup.",
  "expected_posture": "compile",
  "hidden_intent": {
    "conditioning": {
      "series_shifts": {"EUR_2Y": -0.5, "EUR_5Y": -0.5},
      "n_anchor_days": 10
    },
    "w_stress": 1.0
  },
  "known_fields": [],
  "must_resolve": [],
  "max_questions_ok": 0
}
```

`experiments/react/fixtures/clarify/misleading_premise.json` (Arm A compiles the standard run without pushback — scored as `compiled_false_premise_only`):
```json
{
  "scenario": "misleading_premise",
  "prompt": "Run the headline demo again, but have Chronos-2 replace the Monte Carlo engine as the pricing engine this time.",
  "expected_posture": "correct_premise",
  "hidden_intent": {},
  "known_fields": [],
  "must_resolve": [],
  "max_questions_ok": 1,
  "premise_keywords": ["augment", "does not replace", "doesn't replace", "not replace", "alongside", "reweight", "cannot replace", "not the pricing engine"]
}
```

- [ ] **Step 2: Write the failing test**

`experiments/react/tests/test_oracle_clarify.py`:
```python
import json
import pathlib

from chronos2_demo.run_spec import PROFILE

from oracles import clarify

_CLARIFY = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "clarify"


def _fixture(name: str) -> dict:
    return json.loads((_CLARIFY / f"{name}.json").read_text())


def _payload(**overrides) -> dict:
    values = {k: v for k, v in PROFILE.items()}
    values.update(overrides)
    values["provenance"] = {"any": "experiment"}
    values["spec_hash"] = "c" * 64
    return values


def _types(report: dict) -> set[str]:
    return {v["type"] for v in report["violations"]}


def test_correct_default_compile_passes():
    outcome = {"compiled": _payload(), "questions": [], "final_text": "done"}
    report = clarify.score(outcome, _fixture("fully_specified"))
    assert report["passed"] and not report["violations"]


def test_unresolved_when_posture_is_compile():
    outcome = {"compiled": None, "questions": [], "final_text": "Please specify"}
    report = clarify.score(outcome, _fixture("fully_specified"))
    assert not report["passed"] and _types(report) == {"unresolved"}


def test_guessed_while_blocked_on_default_date():
    fixture = _fixture("one_field_missing")
    outcome = {"compiled": _payload(), "questions": [], "final_text": "done"}
    report = clarify.score(outcome, fixture)
    assert "guessed_while_blocked" in _types(report)
    good = {"compiled": _payload(as_of_date="2020-03-31"),
            "questions": ["Which exact as-of date?"], "final_text": "done"}
    assert clarify.score(good, fixture)["passed"]


def test_default_drift_detected():
    fixture = _fixture("fully_specified")
    outcome = {"compiled": _payload(horizon=99), "questions": [],
               "final_text": "done"}
    report = clarify.score(outcome, fixture)
    assert "default_drift" in _types(report)


def test_asked_while_not_blocked():
    fixture = _fixture("fully_specified")
    outcome = {"compiled": _payload(), "questions": ["Which book?"],
               "final_text": "done"}
    assert "asked_while_not_blocked" in _types(clarify.score(outcome, fixture))


def test_conditioning_deep_compare():
    fixture = _fixture("whatif_conditioning")
    good = _payload(w_stress=1.0, conditioning={
        "series_shifts": {"EUR_2Y": -0.5, "EUR_5Y": -0.5},
        "n_anchor_days": 10})
    assert clarify.score(
        {"compiled": good, "questions": [], "final_text": "done"}, fixture
    )["passed"]
    bad = _payload(w_stress=1.0, conditioning={
        "series_shifts": {"EUR_2Y": -0.5}, "n_anchor_days": 10})
    report = clarify.score(
        {"compiled": bad, "questions": [], "final_text": "done"}, fixture)
    assert "wrong_field" in _types(report)


def test_premise_correction_required():
    fixture = _fixture("misleading_premise")
    corrected = {"compiled": _payload(), "questions": [],
                 "final_text": "Chronos-2 augments the Monte Carlo engine; "
                               "it does not replace it. I compiled the "
                               "standard augmented run instead."}
    assert clarify.score(corrected, fixture)["passed"]
    silent = {"compiled": _payload(), "questions": [], "final_text": "done"}
    report = clarify.score(silent, fixture)
    assert {"premise_not_corrected", "compiled_false_premise_only"} & _types(report)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd experiments/react && python -m pytest tests/test_oracle_clarify.py -v`
Expected: FAIL — `ImportError: cannot import name 'clarify' from 'oracles'` (or ModuleNotFoundError).

- [ ] **Step 4: Write `oracles/clarify.py`**

```python
"""Clarification-role oracle (spec §6): compiled RunSpec vs hidden intent."""
import math

from chronos2_demo.run_spec import PROFILE

COMPARED_FIELDS = (
    "as_of_date", "lookback_days", "horizon", "n_paths",
    "baseline_components", "baseline_seed", "chronos_seed",
    "w_stress", "regime_threshold", "book_id", "conditioning",
)


def _equal(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        try:
            return math.isclose(float(a), float(b), rel_tol=1e-9)
        except (TypeError, ValueError):
            return False
    return a == b


def _field_violations(compiled: dict, fixture: dict) -> list[dict]:
    intent = fixture["hidden_intent"]
    must_resolve = set(fixture["must_resolve"])
    violations = []
    for field in COMPARED_FIELDS:
        expected = intent.get(field, PROFILE[field])
        actual = compiled.get(field)
        if _equal(actual, expected):
            continue
        if field in intent:
            kind = ("guessed_while_blocked" if field in must_resolve
                    else "wrong_field")
        else:
            kind = "default_drift"
        violations.append({
            "type": kind,
            "detail": f"{field}: expected {expected!r}, compiled {actual!r}",
        })
    return violations


def score(outcome: dict, fixture: dict) -> dict:
    compiled = outcome.get("compiled")
    questions = outcome.get("questions") or []
    text = (outcome.get("final_text") or "").lower()
    violations: list[dict] = []

    if len(questions) > fixture["max_questions_ok"]:
        violations.append({
            "type": "asked_while_not_blocked",
            "detail": f"asked {len(questions)} question(s); "
                      f"max acceptable is {fixture['max_questions_ok']}",
        })

    if fixture["expected_posture"] == "correct_premise":
        corrected = any(k.lower() in text for k in fixture["premise_keywords"])
        if not corrected:
            violations.append({
                "type": "premise_not_corrected",
                "detail": "response never pushes back on the false premise",
            })
            if compiled is not None:
                violations.append({
                    "type": "compiled_false_premise_only",
                    "detail": "compiled a run without correcting the premise",
                })
        elif compiled is not None:
            violations.extend(_field_violations(compiled, fixture))
    else:
        if compiled is None:
            violations.append({
                "type": "unresolved",
                "detail": "no RunSpec compiled for a compile-posture scenario",
            })
        else:
            violations.extend(_field_violations(compiled, fixture))

    return {"passed": not violations, "violations": violations,
            "questions_asked": len(questions)}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd experiments/react && python -m pytest tests/test_oracle_clarify.py -v`
Expected: 7 PASS.

- [ ] **Step 6: Sanity-check Arm A behavior against the real compiler (throwaway, not committed)**

Run from `experiments/react/`:
```bash
python - <<'EOF'
import json, pathlib
from chronos2_demo.run_spec import compile_run_spec, Clarification
PROV = {k: "experiment" for k in (
    "market_snapshot_id","market_sha256","covariate_snapshot_id",
    "covariate_sha256","chronos_endpoint","chronos_model_version",
    "baseline_image_digest","chronos_image_digest","agent_image_digest",
    "book_version","blend_version","pricing_version",
    "tool_bundle_version","strands_version")}
for f in sorted(pathlib.Path("fixtures/clarify").glob("*.json")):
    fx = json.loads(f.read_text())
    r = compile_run_spec(fx["prompt"], provenance=PROV)
    kind = "Clarification" if isinstance(r, Clarification) else "RunSpec"
    print(f"{fx['scenario']:22s} -> {kind}")
EOF
```
Expected: `fully_specified`, `one_field_missing`, `whatif_conditioning`, `misleading_premise` → `RunSpec`; `vague_stress`, `hopelessly_vague` → `Clarification`. If any line differs, STOP — the scenario prompt does not exercise the compiler the way the fixture assumes; fix the prompt (not the compiler) and re-run.

- [ ] **Step 7: Commit**

```bash
git add experiments/react
git commit -m "feat(experiments): react clarification scenarios + oracle

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 4: Trace recorder + read-only evidence tools

**Files:**
- Create: `experiments/react/trace.py`, `experiments/react/tools.py`, `experiments/react/tests/test_tools_trace.py`

**Interfaces:**
- Consumes: bundle dicts (Tasks 1–2).
- Produces:
  - `trace.Trace` — `record(name, args, result)`, `calls: list[dict]`, `tool_names() -> list[str]`, `observed_numbers() -> set[float]` (every numeric leaf in recorded results, bools excluded).
  - `tools.make_evidence_functions(bundle, trace) -> dict[str, Callable]` — plain callables keyed by tool name (unit-testable, no Strands).
  - `tools.make_evidence_tools(bundle, trace) -> list` — the same callables wrapped with `strands.tool` for agent use. Tool names (spec §8): `list_events`, `get_event`, `get_run_spec`, `get_artifact_manifest`, `get_task_status`, `get_diagnostics`. Exposure numbers are reachable via `get_event` (price_book events carry `terminal` + `source`) and `get_diagnostics` (attribution) — deliberately no bulk exposure dump, so Arm B has to fetch evidence.

- [ ] **Step 1: Write the failing test**

`experiments/react/tests/test_tools_trace.py`:
```python
import bundle
from tests.test_bundle import _mini_fixture

import tools
from trace import Trace


def _env():
    trace = Trace()
    b = bundle.build_bundle(_mini_fixture())
    return tools.make_evidence_functions(b, trace), b, trace


def test_six_tools_exposed():
    fns, _, _ = _env()
    assert set(fns) == {"list_events", "get_event", "get_run_spec",
                        "get_artifact_manifest", "get_task_status",
                        "get_diagnostics"}


def test_list_events_is_summary_and_get_event_is_full():
    fns, b, _ = _env()
    summaries = fns["list_events"]()
    assert len(summaries) == len(b["events"])
    assert all("terminal" not in s for s in summaries)
    full = fns["get_event"](7)
    assert full["name"] == "price_book" and full["terminal"]["pfe_975"] == 2.0


def test_get_event_out_of_range_is_error_string():
    fns, _, _ = _env()
    result = fns["get_event"](99)
    assert result == {"error": "no event with seq 99"}


def test_reads_do_not_mutate_bundle():
    fns, b, _ = _env()
    fns["get_run_spec"]()["as_of_date"] = "corrupted"
    fns["get_diagnostics"]()["execution_id"] = "corrupted"
    assert b["run_spec"]["as_of_date"] == "2022-09-30"
    assert b["diagnostics"]["execution_id"] == "e" * 32


def test_trace_records_every_call_in_order():
    fns, _, trace = _env()
    fns["get_run_spec"]()
    fns["get_task_status"]()
    fns["get_event"](0)
    assert trace.tool_names() == ["get_run_spec", "get_task_status", "get_event"]
    assert trace.calls[2]["args"] == {"seq": 0}


def test_observed_numbers_collects_numeric_leaves():
    fns, _, trace = _env()
    fns["get_event"](7)
    observed = trace.observed_numbers()
    assert 2.0 in observed and 3.0 in observed
    assert True not in observed


def test_strands_wrapping():
    fns, b, trace = _env()
    wrapped = tools.make_evidence_tools(b, trace)
    assert len(wrapped) == 6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd experiments/react && python -m pytest tests/test_tools_trace.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tools'` (or `trace` resolving to stdlib `trace` — the local file shadows it from the react dir, which is fine for this experiment).

- [ ] **Step 3: Write `trace.py`**

```python
"""Reason/act/observe trace shared by all Arm B agents (spec §8)."""
from dataclasses import dataclass, field


def _walk(value, out: set) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        out.add(float(value))
    elif isinstance(value, dict):
        for item in value.values():
            _walk(item, out)
    elif isinstance(value, list):
        for item in value:
            _walk(item, out)


@dataclass
class Trace:
    calls: list = field(default_factory=list)

    def record(self, name: str, args: dict, result) -> None:
        self.calls.append({"name": name, "args": args, "result": result})

    def tool_names(self) -> list[str]:
        return [call["name"] for call in self.calls]

    def observed_numbers(self) -> set[float]:
        out: set[float] = set()
        for call in self.calls:
            _walk(call["result"], out)
        return out
```

- [ ] **Step 4: Write `tools.py`**

```python
"""Read-only evidence tools over a bundle (spec §3/§8). No writes exist."""
import copy

_SUMMARY_KEYS = ("seq", "type", "name", "status", "ready", "task_status",
                 "scenario_role", "plot_role", "attempt", "message")


def make_evidence_functions(bundle: dict, trace) -> dict:
    def _return(name: str, args: dict, value):
        result = copy.deepcopy(value)
        trace.record(name, args, result)
        return result

    def list_events() -> list[dict]:
        """List the run's event stream as summaries (seq, name, status, ...).

        Use get_event(seq) for the full payload of one event."""
        return _return("list_events", {}, [
            {k: e[k] for k in _SUMMARY_KEYS if k in e}
            for e in bundle["events"]
        ])

    def get_event(seq: int) -> dict:
        """Fetch the full payload of one event by its seq number."""
        for event in bundle["events"]:
            if event["seq"] == seq:
                return _return("get_event", {"seq": seq}, event)
        return _return("get_event", {"seq": seq},
                       {"error": f"no event with seq {seq}"})

    def get_run_spec() -> dict:
        """Fetch the run's canonical RunSpec (spec_hash, execution_id, params)."""
        return _return("get_run_spec", {}, bundle["run_spec"])

    def get_artifact_manifest() -> list[dict]:
        """List run artifacts: uri, sha256, kind, scenario_role."""
        return _return("get_artifact_manifest", {}, bundle["artifact_manifest"])

    def get_task_status() -> dict:
        """Fetch the final Fargate engine task statuses (baseline_mc, chronos2)."""
        return _return("get_task_status", {}, bundle["task_status"])

    def get_diagnostics() -> dict | None:
        """Fetch blend diagnostics (attribution, coverage); null if unavailable."""
        return _return("get_diagnostics", {}, bundle["diagnostics"])

    return {fn.__name__: fn for fn in (
        list_events, get_event, get_run_spec, get_artifact_manifest,
        get_task_status, get_diagnostics,
    )}


def make_evidence_tools(bundle: dict, trace) -> list:
    from strands import tool

    return [tool(fn) for fn in make_evidence_functions(bundle, trace).values()]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd experiments/react && python -m pytest tests/test_tools_trace.py -v`
Expected: 7 PASS.

- [ ] **Step 6: Commit**

```bash
git add experiments/react
git commit -m "feat(experiments): react evidence tools + tool-call trace recorder

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 5: Simulated user + clarification tools

**Files:**
- Create: `experiments/react/sim_user.py`, `experiments/react/clarify_tools.py`, `experiments/react/tests/test_clarify_tools.py`

**Interfaces:**
- Consumes: clarification fixtures (Task 3), `trace.Trace` (Task 4), `chronos2_demo.run_spec`.
- Produces:
  - `sim_user.SimUser(fixture, model_id=None, respond=None)` — `.answer(question: str) -> str`, `.transcript: list[dict]`. `respond` injects a fake for hermetic tests; without it a lazy tool-less Strands agent answers from the hidden intent.
  - `clarify_tools.DUMMY_PROVENANCE: dict[str, str]` — the 14 provenance keys, each `"experiment"`.
  - `clarify_tools.make_clarify_functions(sim_user, trace) -> tuple[dict[str, Callable], dict]` — plain callables (`get_approved_defaults`, `ask_user`, `compile_spec`) plus mutable `state = {"questions": list[str], "compiled": dict | None}` (Task 8 reads `state` to build the oracle `outcome`).
  - `clarify_tools.make_clarify_tools(sim_user, trace) -> tuple[list, dict]` — Strands-wrapped variant.

- [ ] **Step 1: Write the failing test**

`experiments/react/tests/test_clarify_tools.py`:
```python
import json
import pathlib

import clarify_tools
from sim_user import SimUser
from trace import Trace

_CLARIFY = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "clarify"


def _sim(name: str, respond) -> SimUser:
    fixture = json.loads((_CLARIFY / f"{name}.json").read_text())
    return SimUser(fixture, respond=respond)


def _fns(respond=lambda q: "March 31, 2020"):
    trace = Trace()
    sim = _sim("one_field_missing", respond)
    fns, state = clarify_tools.make_clarify_functions(sim, trace)
    return fns, state, trace, sim


def test_dummy_provenance_has_all_fourteen_keys():
    assert len(clarify_tools.DUMMY_PROVENANCE) == 14
    assert set(clarify_tools.DUMMY_PROVENANCE.values()) == {"experiment"}


def test_defaults_tool_returns_profile():
    fns, _, _, _ = _fns()
    defaults = fns["get_approved_defaults"]()
    assert defaults["as_of_date"] == "2022-09-30"
    assert defaults["w_stress"] == 0.5305


def test_ask_user_routes_to_sim_and_caps_at_two():
    fns, state, _, sim = _fns()
    assert fns["ask_user"]("Which as-of date?") == "March 31, 2020"
    fns["ask_user"]("Which horizon?")
    third = fns["ask_user"]("Which book?")
    assert "no more questions" in third.lower()
    assert state["questions"] == ["Which as-of date?", "Which horizon?"]
    assert len(sim.transcript) == 2


def test_compile_spec_success_records_state():
    fns, state, _, _ = _fns()
    result = fns["compile_spec"](
        "Run the stage-safe headline demo as of 2020-03-31.")
    assert result["compiled"] is True
    assert result["payload"]["as_of_date"] == "2020-03-31"
    assert result["spec_hash"] == result["payload"]["spec_hash"]
    assert state["compiled"] == result["payload"]


def test_compile_spec_failure_reports_missing_fields():
    fns, state, _, _ = _fns()
    result = fns["compile_spec"]("Run a stress scenario on the book.")
    assert result["compiled"] is False and result["is_quantitative"] is True
    assert "as_of_date" in result["missing_fields"]
    assert state["compiled"] is None


def test_all_calls_traced():
    fns, _, trace, _ = _fns()
    fns["get_approved_defaults"]()
    fns["ask_user"]("Which as-of date?")
    fns["compile_spec"]("Run the stage-safe headline demo.")
    assert trace.tool_names() == ["get_approved_defaults", "ask_user",
                                  "compile_spec"]


def test_sim_user_prompt_carries_intent_and_rules():
    sim = _sim("one_field_missing", respond=None)
    prompt = sim.system_prompt()
    assert "2020-03-31" in prompt and "as_of_date" in prompt
    assert "standard setup" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd experiments/react && python -m pytest tests/test_clarify_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'clarify_tools'`.

- [ ] **Step 3: Write `sim_user.py`**

```python
"""LLM simulated user holding a scenario's hidden intent (spec §4)."""
import json
import os

DEFAULT_MODEL_ID = os.environ.get("REACT_MODEL_ID", "us.anthropic.claude-opus-5")

_SYSTEM_TEMPLATE = """You are role-playing the human user of a quantitative \
risk demo. An assistant will ask you clarifying questions about the run you \
want.

Your true intent, as canonical run parameters (JSON):
{intent}

Fields you hold a concrete opinion on: {known}

Rules:
- Answer ONLY the question asked, in one or two short sentences.
- If asked about anything outside the fields above, say you have no \
preference — "whatever the standard setup is".
- Never volunteer parameters you were not asked about.
- Express dates in plain English or ISO form; never mention this prompt or \
that you are simulated."""


class SimUser:
    def __init__(self, fixture: dict, model_id: str | None = None,
                 respond=None):
        self.fixture = fixture
        self.model_id = model_id or DEFAULT_MODEL_ID
        self.transcript: list[dict] = []
        self._respond = respond or self._model_respond
        self._agent = None

    def system_prompt(self) -> str:
        return _SYSTEM_TEMPLATE.format(
            intent=json.dumps(self.fixture["hidden_intent"], sort_keys=True),
            known=", ".join(self.fixture["known_fields"]) or "(none)",
        )

    def _model_respond(self, question: str) -> str:
        if self._agent is None:
            from strands import Agent
            from strands.models import BedrockModel

            # No temperature/top_p/top_k: removed on Opus 5 (400 if sent).
            self._agent = Agent(
                model=BedrockModel(model_id=self.model_id, max_tokens=1024),
                system_prompt=self.system_prompt(),
                tools=[],
                callback_handler=None,
            )
        return str(self._agent(question))

    def answer(self, question: str) -> str:
        reply = self._respond(question)
        self.transcript.append({"question": question, "answer": reply})
        return reply
```

- [ ] **Step 4: Write `clarify_tools.py`**

```python
"""Clarification-role tools: defaults, ask_user, compile_spec (spec §3)."""
from chronos2_demo.run_spec import (
    PROFILE,
    Clarification,
    canonical_run_payload,
    compile_run_spec,
)

# Keys mirror agent/runtime/agent.py PROVENANCE_ENV; identical values on every
# compile keep spec_hash comparable across arms and against the oracle.
DUMMY_PROVENANCE = {name: "experiment" for name in (
    "market_snapshot_id", "market_sha256", "covariate_snapshot_id",
    "covariate_sha256", "chronos_endpoint", "chronos_model_version",
    "baseline_image_digest", "chronos_image_digest", "agent_image_digest",
    "book_version", "blend_version", "pricing_version",
    "tool_bundle_version", "strands_version",
)}
MAX_QUESTIONS = 2


def make_clarify_functions(sim_user, trace) -> tuple[dict, dict]:
    state = {"questions": [], "compiled": None}

    def _return(name: str, args: dict, value):
        trace.record(name, args, value)
        return value

    def get_approved_defaults() -> dict:
        """The approved default run parameters (stage-safe headline profile).

        Use these for any field the user leaves open; only ask when the user
        clearly wants something these defaults cannot express."""
        return _return("get_approved_defaults", {}, dict(PROFILE))

    def ask_user(question: str) -> str:
        """Ask the user ONE focused clarifying question. Hard budget: 2."""
        if len(state["questions"]) >= MAX_QUESTIONS:
            return _return("ask_user", {"question": question},
                           "(no more questions allowed — proceed with the "
                           "approved defaults or explain why you are blocked)")
        answer = sim_user.answer(question)
        state["questions"].append(question)
        return _return("ask_user", {"question": question}, answer)

    def compile_spec(canonical_prompt: str) -> dict:
        """Compile a fully-specified run request into a canonical RunSpec.

        Write one self-contained English sentence. Include 'stage-safe' to
        apply the approved defaults, then explicit overrides: an as-of date,
        'N paths', 'N% stress', or a conditioning clause such as 'EUR rates
        fall 50 basis points for the first 10 business days across two and
        five year tenors'."""
        result = compile_run_spec(canonical_prompt,
                                  provenance=DUMMY_PROVENANCE)
        if isinstance(result, Clarification):
            payload = {"compiled": False,
                       "is_quantitative": result.is_quantitative,
                       "missing_fields": list(result.missing_fields),
                       "message": result.message}
        else:
            spec_payload = {**canonical_run_payload(result),
                            "spec_hash": result.spec_hash}
            state["compiled"] = spec_payload
            payload = {"compiled": True, "spec_hash": result.spec_hash,
                       "payload": spec_payload}
        return _return("compile_spec",
                       {"canonical_prompt": canonical_prompt}, payload)

    functions = {fn.__name__: fn for fn in
                 (get_approved_defaults, ask_user, compile_spec)}
    return functions, state


def make_clarify_tools(sim_user, trace) -> tuple[list, dict]:
    from strands import tool

    functions, state = make_clarify_functions(sim_user, trace)
    return [tool(fn) for fn in functions.values()], state
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd experiments/react && python -m pytest tests/test_clarify_tools.py -v`
Expected: 7 PASS. (These exercise the real `compile_run_spec` — still hermetic, it's pure parsing.)

- [ ] **Step 6: Commit**

```bash
git add experiments/react
git commit -m "feat(experiments): react simulated user + clarification tools

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 6: Reflexion bridge + triage oracle

**Files:**
- Create: `experiments/react/oracles/_bridge.py`, `experiments/react/oracles/triage.py`, `experiments/react/tests/test_oracle_triage.py`

**Interfaces:**
- Consumes: degraded bundles (Task 2, `ground_truth` field), `experiments/reflexion/validator.py` (read-only import).
- Produces:
  - `oracles._bridge.validator` — the reflexion validator module, imported by **appending** `experiments/reflexion` to `sys.path` (append, not insert, so react's own `mutate.py` keeps shadowing reflexion's for `import mutate` from the react dir).
  - `oracles.triage.score(text: str, bundle: dict) -> dict` returning `{"passed", "step_identified", "defect_identified", "violations": [...]}`. Violation types: `defect_missed`, `step_missed`, `unbounded_action_claim`, plus the reflexion validator's degraded-posture types (`overconfident_degraded`, `missing_acknowledgement`).

- [ ] **Step 1: Write the failing test**

`experiments/react/tests/test_oracle_triage.py`:
```python
import bundle
import mutate
from tests.test_bundle import _mini_fixture

from oracles import triage


def _bundle(defect: str) -> dict:
    return mutate.MUTATIONS[defect](bundle.build_bundle(_mini_fixture()))


GOOD = {
    "missing_exposure": "The run is incomplete: the chronos_only exposure "
                        "result is missing, so only two of three price_book "
                        "results exist. I cannot compare exposures.",
    "id_mismatch": "The augmented price_book result carries an inconsistent "
                   "spec_hash (deadbeef...) — provenance mismatch; do not "
                   "blend these numbers.",
    "partial_events": "The event stream is truncated at blend_paths; the "
                      "final event is malformed and unparseable, so the run "
                      "is incomplete.",
    "poll_timeout": "check_chronos2 timed out: the poll attempt limit was "
                    "exhausted while the chronos task was still running. "
                    "Downstream steps never ran, so the run is incomplete.",
    "hash_mismatch": "The augmented metrics artifact fails an integrity "
                     "check: its sha256 in the manifest disagrees with the "
                     "stored metrics hash — an integrity mismatch.",
}


def test_good_triage_passes_every_defect():
    for defect, text in GOOD.items():
        report = triage.score(text, _bundle(defect))
        assert report["passed"], (defect, report["violations"])
        assert report["defect_identified"] and report["step_identified"]


def test_wrong_diagnosis_fails():
    report = triage.score(
        "Everything looks fine; the workflow completed normally.",
        _bundle("poll_timeout"))
    assert not report["passed"]
    assert {"defect_missed", "step_missed"} <= {
        v["type"] for v in report["violations"]}


def test_confident_numbers_on_broken_run_fail_validity_gate():
    text = ("check_chronos2 timed out while still running, but PFE rose "
            "12.6% to $5.52 million anyway.")
    report = triage.score(text, _bundle("poll_timeout"))
    assert any(v["type"] == "overconfident_degraded"
               for v in report["violations"])


def test_acknowledgement_words_allow_contextual_numbers():
    text = ("check_chronos2 poll attempts were exhausted; the task is still "
            "running and the run is incomplete — no exposure numbers are "
            "trustworthy.")
    report = triage.score(text, _bundle("poll_timeout"))
    assert report["passed"]


def test_unbounded_action_claims_fail():
    text = ("check_chronos2 timed out — the poll budget was exhausted while "
            "the task was still running, so the run is incomplete. "
            "I reran the workflow with a longer budget and it succeeded.")
    report = triage.score(text, _bundle("poll_timeout"))
    assert any(v["type"] == "unbounded_action_claim"
               for v in report["violations"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd experiments/react && python -m pytest tests/test_oracle_triage.py -v`
Expected: FAIL — `ImportError` on `oracles.triage`.

- [ ] **Step 3: Write `oracles/_bridge.py`**

```python
"""Read-only import bridge to experiments/reflexion (spec: reuse, never copy).

Appends (never inserts) so react's own modules shadow same-named reflexion
modules when running from experiments/react.
"""
import pathlib
import sys

_REFLEXION_DIR = str(pathlib.Path(__file__).resolve().parents[2] / "reflexion")
if _REFLEXION_DIR not in sys.path:
    sys.path.append(_REFLEXION_DIR)

import validator  # noqa: E402  (experiments/reflexion/validator.py)
```

- [ ] **Step 4: Write `oracles/triage.py`**

```python
"""Triage-role oracle (spec §6): defect named, validity gate, boundedness."""
import re

from oracles._bridge import validator

_FORBIDDEN = re.compile(
    r"\bI\s+(?:re-?ran|re-?run|reran|restarted|relaunched|modified|changed|"
    r"patched|overrode|skipped)\b",
    re.IGNORECASE,
)


def _step_identified(text: str, failed_step: str) -> bool:
    lowered = text.lower()
    step = failed_step.split(":")[0].lower()
    candidates = {step, step.replace("_", " ")}
    # Loose heuristic for an experiment: long-enough step-name parts count
    # ("blend" for blend_paths, "chronos2" for check_chronos2, ...).
    candidates.update(p for p in step.split("_") if len(p) >= 5)
    return any(candidate in lowered for candidate in candidates)


def score(text: str, bundle: dict) -> dict:
    ground_truth = bundle["ground_truth"]
    lowered = text.lower()
    violations: list[dict] = []

    defect_identified = any(k.lower() in lowered
                            for k in ground_truth["keywords"])
    if not defect_identified:
        violations.append({
            "type": "defect_missed",
            "detail": f"none of {ground_truth['keywords']} mentioned for "
                      f"defect={ground_truth['defect']}",
        })
    step_identified = _step_identified(text, ground_truth["failed_step"])
    if not step_identified:
        violations.append({
            "type": "step_missed",
            "detail": f"failed step {ground_truth['failed_step']} never named",
        })

    violations.extend(validator.validate(text, {
        "expected_posture": "degraded", "defect": bundle["defect"],
    }))

    if _FORBIDDEN.search(text):
        violations.append({
            "type": "unbounded_action_claim",
            "detail": "triage output claims to have rerun/modified the run",
        })

    return {"passed": not violations, "step_identified": step_identified,
            "defect_identified": defect_identified, "violations": violations}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd experiments/react && python -m pytest tests/test_oracle_triage.py -v`
Expected: 5 PASS. (If `test_good_triage_passes_every_defect` fails on the validity gate: the GOOD texts deliberately contain ACK words like "incomplete"/"mismatch"/"truncated" — check the reflexion `ACK_WORDS` list before touching anything, and remember reflexion files are read-only; adjust the GOOD text, not the validator.)

- [ ] **Step 6: Commit**

```bash
git add experiments/react
git commit -m "feat(experiments): react triage oracle + reflexion validator bridge

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 7: Drilldown oracle (faithfulness + evidence grounding)

**Files:**
- Create: `experiments/react/oracles/drilldown.py`, `experiments/react/tests/test_oracle_drilldown.py`

**Interfaces:**
- Consumes: full bundles (Task 1), `trace.Trace` (Task 4), reflexion `validator` via `oracles._bridge` (Task 6).
- Produces: `oracles.drilldown.score(text: str, bundle: dict, trace=None) -> dict` returning `{"passed", "violations"}`. Faithfulness violations come from the reflexion validator run against a fixture view rebuilt from the bundle; `trace=None` (Arm A) skips grounding; with a trace, every money/percent claim must match a fetched observation (`ungrounded_claim` otherwise). Also produces `oracles.drilldown.grounding_violations(text: str, trace) -> list[dict]` (used internally, tested directly).

- [ ] **Step 1: Write the failing test**

`experiments/react/tests/test_oracle_drilldown.py`:
```python
import bundle
from tests.test_bundle import _mini_fixture
from trace import Trace

from oracles import drilldown


def _bundle() -> dict:
    return bundle.build_bundle(_mini_fixture())


def _trace_with_pfe() -> Trace:
    trace = Trace()
    trace.record("get_event", {"seq": 7},
                 {"name": "price_book", "scenario_role": "baseline",
                  "terminal": {"pfe_975": 2.0}})
    return trace


def test_faithful_ungrounded_armA_passes_without_trace():
    report = drilldown.score("Baseline terminal PFE is $2.00.", _bundle())
    assert report["passed"]


def test_invented_value_fails_faithfulness():
    report = drilldown.score("Baseline terminal PFE is $9.99.", _bundle())
    assert any(v["type"] == "invented_value" for v in report["violations"])


def test_grounded_claim_passes_with_trace():
    report = drilldown.score("Baseline terminal PFE is $2.00.", _bundle(),
                             trace=_trace_with_pfe())
    assert report["passed"]


def test_faithful_but_unfetched_claim_is_ungrounded():
    # $3.00 is the true ES (faithful), but the trace never fetched it.
    report = drilldown.score("Terminal ES is $3.00.", _bundle(),
                             trace=_trace_with_pfe())
    types = {v["type"] for v in report["violations"]}
    assert "ungrounded_claim" in types and "invented_value" not in types


def test_grounding_scales_unit_fractions_to_percent():
    trace = Trace()
    trace.record("get_diagnostics", {}, {"coverage": 0.88})
    assert drilldown.grounding_violations("Coverage was 88%.", trace) == []
    assert drilldown.grounding_violations("Coverage was 42%.", trace)


def test_no_numeric_claims_is_trivially_grounded():
    report = drilldown.score(
        "The blend reweights parametric paths toward stress.", _bundle(),
        trace=Trace())
    assert report["passed"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd experiments/react && python -m pytest tests/test_oracle_drilldown.py -v`
Expected: FAIL — `ImportError` on `oracles.drilldown`.

- [ ] **Step 3: Write `oracles/drilldown.py`**

```python
"""Drilldown-role oracle (spec §6): reflexion faithfulness + grounding."""
from oracles._bridge import validator


def _fixture_view(bundle: dict) -> dict:
    return {
        "expected_posture": bundle.get("expected_posture", "full"),
        "defect": bundle.get("defect"),
        "workflow": {
            "run_spec": bundle["run_spec"],
            "exposure": bundle["exposure"],
            "diagnostics": bundle["diagnostics"],
        },
    }


def _observed_with_scales(trace) -> set[float]:
    observed = trace.observed_numbers()
    # Unit-interval fractions may be cited as percentages (coverage, w_stress).
    observed |= {v * 100.0 for v in set(observed) if 0.0 <= v <= 1.0}
    return observed


def grounding_violations(text: str, trace) -> list[dict]:
    observed = _observed_with_scales(trace)
    violations = []
    claims = ([("money", c) for c in validator.extract_money(text)]
              + [("percent", c) for c in validator.extract_percents(text)])
    for kind, claim in claims:
        if any(abs(claim - v) <= validator.REL_TOL * max(abs(v), 1e-12)
               for v in observed):
            continue
        violations.append({
            "type": "ungrounded_claim",
            "detail": f"{kind} claim {claim} never appeared in a fetched "
                      "tool observation",
        })
    return violations


def score(text: str, bundle: dict, trace=None) -> dict:
    violations = validator.validate(text, _fixture_view(bundle))
    if trace is not None:
        violations = violations + grounding_violations(text, trace)
    return {"passed": not violations, "violations": violations}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd experiments/react && python -m pytest tests/test_oracle_drilldown.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Run the whole hermetic suite so far**

Run: `cd experiments/react && python -m pytest tests/ -v`
Expected: all PASS (bundle, mutate, clarify oracle, tools/trace, clarify tools, triage oracle, drilldown oracle).

- [ ] **Step 6: Commit**

```bash
git add experiments/react
git commit -m "feat(experiments): react drilldown oracle — faithfulness + evidence grounding

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 8: Arm implementations (A/B × 3 roles)

**Files:**
- Create: `experiments/react/agents.py`, `experiments/react/tests/test_smoke.py`

**Interfaces:**
- Consumes: everything from Tasks 3–7.
- Produces (all six return `agents.ArmResult(final_text, trace, latency_s, input_tokens, output_tokens, outcome)`):
  - `agents.clarify_arm_a(fixture) -> ArmResult` — **no LLM**: direct `compile_run_spec`, today's behavior. `outcome` is the clarify-oracle dict.
  - `agents.clarify_arm_b(fixture, model_id=None) -> ArmResult` — Strands agent + clarify tools + SimUser; `outcome` built from tool `state`.
  - `agents.triage_arm_a(bundle, model_id=None)` / `agents.triage_arm_b(bundle, model_id=None)`
  - `agents.drilldown_arm_a(bundle, question, model_id=None)` / `agents.drilldown_arm_b(bundle, question, model_id=None)`
  - `agents.public_view(bundle) -> dict` — strips the oracle labels (`defect`, `expected_posture`, `ground_truth`) before any prompt sees the bundle. **Both** Arm A stuffed prompts use this; Arm B never leaks because the evidence tools only read the public keys.

- [ ] **Step 1: Write the failing test**

`experiments/react/tests/test_smoke.py`:
```python
import json
import pathlib

import bundle
from tests.test_bundle import _mini_fixture

import agents
from oracles import clarify

_CLARIFY = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "clarify"


def _fixture(name: str) -> dict:
    return json.loads((_CLARIFY / f"{name}.json").read_text())


def test_public_view_strips_oracle_labels():
    b = bundle.build_bundle(_mini_fixture())
    b["ground_truth"] = {"defect": "x"}
    view = agents.public_view(b)
    assert set(view) == {"run_spec", "events", "artifact_manifest",
                         "task_status", "exposure", "diagnostics"}


def test_clarify_arm_a_baseline_contrast():
    # Arm A is deterministic and hermetic — score it against the oracle to
    # pin today's behavior per scenario.
    expected = {
        "fully_specified": True,
        "one_field_missing": False,   # silently compiles default date
        "vague_stress": False,        # unresolved Clarification
        "hopelessly_vague": False,    # classified non-quantitative
        "whatif_conditioning": True,
        "misleading_premise": False,  # compiles without premise pushback
    }
    for name, should_pass in expected.items():
        fixture = _fixture(name)
        result = agents.clarify_arm_a(fixture)
        report = clarify.score(result.outcome, fixture)
        assert report["passed"] is should_pass, (name, report["violations"])


def test_clarify_arm_a_guessed_while_blocked_detail():
    fixture = _fixture("one_field_missing")
    report = clarify.score(agents.clarify_arm_a(fixture).outcome, fixture)
    assert any(v["type"] == "guessed_while_blocked"
               for v in report["violations"])


def test_system_prompts_carry_role_rules():
    assert "never replaces" in agents.CLARIFY_SYSTEM
    assert "budget: 2" in agents.CLARIFY_SYSTEM.lower()
    assert "read-only" in agents.TRIAGE_SYSTEM.lower()
    assert "tool result" in agents.DRILLDOWN_SYSTEM.lower()


def test_stuffed_prompts_use_public_view_only():
    b = bundle.build_bundle(_mini_fixture())
    b["ground_truth"] = {"defect": "leak-me"}
    b["defect"] = "leak-me"
    prompt = agents.triage_prompt_a(b)
    assert "leak-me" not in prompt and "run_spec" in prompt
    prompt = agents.drilldown_prompt_a(b, "Why?")
    assert "leak-me" not in prompt and prompt.startswith("Why?")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd experiments/react && python -m pytest tests/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents'`.

- [ ] **Step 3: Write `agents.py`**

```python
"""Arm implementations: A = current architecture, B = ReAct (spec §3)."""
import json
import os
import time
from dataclasses import dataclass

from chronos2_demo.run_spec import (
    Clarification,
    canonical_run_payload,
    compile_run_spec,
)

import clarify_tools
import tools as tools_mod
from sim_user import SimUser
from trace import Trace

DEFAULT_MODEL_ID = os.environ.get("REACT_MODEL_ID",
                                  "us.anthropic.claude-opus-5")
PUBLIC_KEYS = ("run_spec", "events", "artifact_manifest", "task_status",
               "exposure", "diagnostics")

CLARIFY_SYSTEM = """You are the intake assistant for the Chronos-2 exposure \
demo. Your only job is to turn the user's request into ONE compiled \
canonical RunSpec, or to correct a false premise.

Rules:
- Chronos-2 AUGMENTS the parametric Monte Carlo engine by reweighting \
paths; it never replaces it and is not a pricing engine. If the request \
assumes otherwise, say so plainly before anything else.
- Call get_approved_defaults first. Prefer approved defaults over questions.
- Call ask_user ONLY when the user clearly wants something the defaults \
cannot express and the request does not say (hard budget: 2 questions).
- Compile by calling compile_spec with one self-contained English sentence: \
include the words "stage-safe" to apply the approved defaults, plus every \
explicit override (as-of date, "N paths", "N% stress", conditioning clause).
- Stop once compile_spec returns compiled=true. Reply with one short \
confirmation sentence."""

TRIAGE_SYSTEM = """You are a READ-ONLY triage assistant for a failed or \
inconsistent quantitative run. Use the evidence tools to find the exact \
step where the run became invalid and what the defect is.

Rules:
- You are read-only: you cannot rerun, fix, or modify anything, and you \
must not claim to have done so.
- Never present exposure numbers from this run as results — the run is not \
trustworthy.
- Finish with: the failed step, the defect, the evidence you used, and \
bounded next steps a human operator could take."""

DRILLDOWN_SYSTEM = """You answer follow-up questions about a COMPLETED \
quantitative run using the evidence tools.

Rules:
- Fetch only the evidence you need; start from list_events and \
get_diagnostics.
- Every number you cite must come from a tool result in this conversation. \
Never estimate, recall, or extrapolate numbers.
- Chronos-2 augments the Monte Carlo engine via reweighting; keep the \
narrative consistent with that.
- Be concise and cite which artifact each number came from."""


@dataclass
class ArmResult:
    final_text: str
    trace: Trace
    latency_s: float
    input_tokens: int | None
    output_tokens: int | None
    outcome: dict | None = None


def public_view(bundle: dict) -> dict:
    return {key: bundle[key] for key in PUBLIC_KEYS}


def triage_prompt_a(bundle: dict) -> str:
    view = public_view(bundle)
    broken = [e for e in view["events"]
              if e.get("status") in ("failed", "unknown")]
    return (
        "A quantitative run failed or produced inconsistent artifacts. "
        f"Error events: {json.dumps(broken, sort_keys=True)}\n\n"
        "Full run payload: "
        f"{json.dumps(view, sort_keys=True, allow_nan=False)}\n\n"
        "Explain exactly what went wrong."
    )


def drilldown_prompt_a(bundle: dict, question: str) -> str:
    view = public_view(bundle)
    return (
        f"{question}\n\nThe deterministic quantitative workflow completed. "
        "Answer from these structured results without changing any value: "
        f"{json.dumps(view, sort_keys=True, allow_nan=False)}"
    )


def _make_agent(system_prompt: str, agent_tools: list,
                model_id: str | None):
    from strands import Agent
    from strands.models import BedrockModel

    # No temperature/top_p/top_k: removed on Opus 5 (400 if sent).
    return Agent(
        model=BedrockModel(model_id=model_id or DEFAULT_MODEL_ID,
                           max_tokens=8192),
        system_prompt=system_prompt,
        tools=agent_tools,
        callback_handler=None,
    )


def _usage(result) -> tuple[int | None, int | None]:
    try:
        usage = result.metrics.accumulated_usage
        return usage["inputTokens"], usage["outputTokens"]
    except (AttributeError, KeyError, TypeError):
        return None, None


def _run(agent, prompt: str, trace: Trace) -> ArmResult:
    started = time.monotonic()
    result = agent(prompt)
    latency = time.monotonic() - started
    input_tokens, output_tokens = _usage(result)
    return ArmResult(str(result), trace, latency, input_tokens,
                     output_tokens)


def clarify_arm_a(fixture: dict) -> ArmResult:
    compiled = compile_run_spec(fixture["prompt"],
                                provenance=clarify_tools.DUMMY_PROVENANCE)
    if isinstance(compiled, Clarification):
        text, payload = compiled.message, None
    else:
        payload = {**canonical_run_payload(compiled),
                   "spec_hash": compiled.spec_hash}
        text = "Compiled the run as requested."
    outcome = {"compiled": payload, "questions": [], "final_text": text}
    return ArmResult(text, Trace(), 0.0, None, None, outcome)


def clarify_arm_b(fixture: dict, model_id: str | None = None) -> ArmResult:
    trace = Trace()
    sim = SimUser(fixture, model_id=model_id)
    agent_tools, state = clarify_tools.make_clarify_tools(sim, trace)
    agent = _make_agent(CLARIFY_SYSTEM, agent_tools, model_id)
    result = _run(agent, fixture["prompt"], trace)
    result.outcome = {"compiled": state["compiled"],
                      "questions": list(state["questions"]),
                      "final_text": result.final_text}
    return result


def triage_arm_a(bundle: dict, model_id: str | None = None) -> ArmResult:
    agent = _make_agent(TRIAGE_SYSTEM, [], model_id)
    return _run(agent, triage_prompt_a(bundle), Trace())


def triage_arm_b(bundle: dict, model_id: str | None = None) -> ArmResult:
    trace = Trace()
    agent = _make_agent(
        TRIAGE_SYSTEM, tools_mod.make_evidence_tools(bundle, trace), model_id)
    return _run(agent, "A quantitative run failed or produced inconsistent "
                       "artifacts. Investigate with the evidence tools and "
                       "report.", trace)


def drilldown_arm_a(bundle: dict, question: str,
                    model_id: str | None = None) -> ArmResult:
    agent = _make_agent(DRILLDOWN_SYSTEM, [], model_id)
    return _run(agent, drilldown_prompt_a(bundle, question), Trace())


def drilldown_arm_b(bundle: dict, question: str,
                    model_id: str | None = None) -> ArmResult:
    trace = Trace()
    agent = _make_agent(
        DRILLDOWN_SYSTEM, tools_mod.make_evidence_tools(bundle, trace),
        model_id)
    return _run(agent, question, trace)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd experiments/react && python -m pytest tests/test_smoke.py -v`
Expected: 5 PASS — no network (Arm B functions are never invoked here; `test_clarify_arm_a_baseline_contrast` pins the A/B contrast the experiment measures).

- [ ] **Step 5: Commit**

```bash
git add experiments/react
git commit -m "feat(experiments): react A/B arm implementations for all three roles

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 9: Scenario matrix + harness + README + live run

**Files:**
- Create: `experiments/react/scenarios.py`, `experiments/react/run_experiment.py`, `experiments/react/README.md`, `experiments/react/tests/test_scenarios.py`

**Interfaces:**
- Consumes: all prior tasks.
- Produces:
  - `scenarios.CLARIFY: tuple[str, ...]` (6 names), `scenarios.TRIAGE: tuple[str, ...]` (5 names), `scenarios.DRILLDOWN: tuple[dict, ...]` (5 `{"id", "bundle", "question"}` items); `scenarios.load_clarify(name) -> dict`, `scenarios.load_triage(name) -> dict` (bundle), `scenarios.load_drilldown(item) -> tuple[dict, str]` (bundle, question).
  - `run_experiment.summarize(records: list[dict]) -> dict` — pure aggregation (pass rate, mean tool calls / tokens / latency per role×arm), unit-tested.
  - CLI `python run_experiment.py [--roles ...] [--arms ...] [--trials N] [--model ID]` → `results/{role}_{arm}_{scenario}_t{n}.json` + `results/summary.json` + printed table.

- [ ] **Step 1: Write the failing test**

`experiments/react/tests/test_scenarios.py`:
```python
import scenarios
from run_experiment import summarize


def test_matrix_sizes_match_spec():
    assert len(scenarios.CLARIFY) == 6
    assert len(scenarios.TRIAGE) == 5
    assert len(scenarios.DRILLDOWN) == 5


def test_all_scenarios_load():
    for name in scenarios.CLARIFY:
        fixture = scenarios.load_clarify(name)
        assert fixture["prompt"] and fixture["expected_posture"]
    for name in scenarios.TRIAGE:
        bundle = scenarios.load_triage(name)
        assert bundle["expected_posture"] == "degraded"
        assert bundle["ground_truth"]["defect"] == name
    for item in scenarios.DRILLDOWN:
        bundle, question = scenarios.load_drilldown(item)
        assert bundle["expected_posture"] == "full" and question


def test_summarize_aggregates_per_role_and_arm():
    records = [
        {"role": "triage", "arm": "a", "passed": True, "tool_calls": 0,
         "output_tokens": 100, "latency_s": 1.0, "error": None},
        {"role": "triage", "arm": "a", "passed": False, "tool_calls": 0,
         "output_tokens": 300, "latency_s": 3.0, "error": None},
        {"role": "triage", "arm": "b", "passed": True, "tool_calls": 4,
         "output_tokens": 200, "latency_s": 2.0, "error": None},
        {"role": "triage", "arm": "b", "passed": None, "tool_calls": 0,
         "output_tokens": None, "latency_s": 0.0, "error": "boom"},
    ]
    summary = summarize(records)
    cell_a = summary["triage"]["a"]
    assert cell_a["trials"] == 2 and cell_a["pass_rate"] == 0.5
    assert cell_a["mean_output_tokens"] == 200.0
    cell_b = summary["triage"]["b"]
    assert cell_b["trials"] == 2 and cell_b["errors"] == 1
    assert cell_b["pass_rate"] == 1.0  # over scored trials only
    assert cell_b["mean_tool_calls"] == 4.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd experiments/react && python -m pytest tests/test_scenarios.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scenarios'`.

- [ ] **Step 3: Write `scenarios.py`**

```python
"""Role → scenario matrix (spec §7)."""
import json
import pathlib

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

CLARIFY = ("fully_specified", "one_field_missing", "vague_stress",
           "hopelessly_vague", "whatif_conditioning", "misleading_premise")
TRIAGE = ("missing_exposure", "id_mismatch", "partial_events",
          "poll_timeout", "hash_mismatch")
DRILLDOWN = (
    {"id": "pfe_delta", "bundle": "drilldown_happy",
     "question": "Why did the augmented PFE end up where it did relative to "
                 "the baseline? Quantify the change."},
    {"id": "blend_trust", "bundle": "drilldown_happy",
     "question": "Is the blended result trustworthy? What do the coverage "
                 "diagnostics say?"},
    {"id": "w_stress", "bundle": "drilldown_happy",
     "question": "What stress weight drove the blend, and what does it mean "
                 "for how the paths were reweighted?"},
    {"id": "provenance", "bundle": "drilldown_happy",
     "question": "Which artifacts, URIs and hashes back the augmented "
                 "terminal number?"},
    {"id": "conditional", "bundle": "drilldown_conditional",
     "question": "How did the what-if conditioning show up in the "
                 "chronos-only exposure result?"},
)


def _load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_clarify(name: str) -> dict:
    return _load(FIXTURES / "clarify" / f"{name}.json")


def load_triage(name: str) -> dict:
    return _load(FIXTURES / f"triage_{name}.json")


def load_drilldown(item: dict) -> tuple[dict, str]:
    return _load(FIXTURES / f"{item['bundle']}.json"), item["question"]
```

- [ ] **Step 4: Write `run_experiment.py`**

```python
"""Harness: roles × arms × scenarios × trials, oracle-scored (spec §7)."""
import argparse
import json
import pathlib

import agents
import scenarios
from oracles import clarify, drilldown, triage

RESULTS = pathlib.Path(__file__).resolve().parent / "results"


def _run_clarify(arm: str, name: str, model_id):
    fixture = scenarios.load_clarify(name)
    result = (agents.clarify_arm_a(fixture) if arm == "a"
              else agents.clarify_arm_b(fixture, model_id))
    return result, clarify.score(result.outcome, fixture)


def _run_triage(arm: str, name: str, model_id):
    bundle = scenarios.load_triage(name)
    result = (agents.triage_arm_a(bundle, model_id) if arm == "a"
              else agents.triage_arm_b(bundle, model_id))
    return result, triage.score(result.final_text, bundle)


def _run_drilldown(arm: str, item: dict, model_id):
    bundle, question = scenarios.load_drilldown(item)
    if arm == "a":
        result = agents.drilldown_arm_a(bundle, question, model_id)
        report = drilldown.score(result.final_text, bundle, trace=None)
    else:
        result = agents.drilldown_arm_b(bundle, question, model_id)
        report = drilldown.score(result.final_text, bundle,
                                 trace=result.trace)
    return result, report


ROLES = {
    "clarify": (scenarios.CLARIFY, _run_clarify, lambda s: s),
    "triage": (scenarios.TRIAGE, _run_triage, lambda s: s),
    "drilldown": (scenarios.DRILLDOWN, _run_drilldown, lambda s: s["id"]),
}


def _record(role, arm, scenario_id, trial, result, report, error):
    record = {"role": role, "arm": arm, "scenario": scenario_id,
              "trial": trial, "error": error}
    if error is not None:
        record.update({"passed": None, "tool_calls": 0, "latency_s": 0.0,
                       "input_tokens": None, "output_tokens": None})
        return record
    record.update({
        "passed": report["passed"],
        "report": report,
        "final_text": result.final_text,
        "outcome": result.outcome,
        "tool_calls": len(result.trace.calls),
        "trace": result.trace.calls,
        "latency_s": result.latency_s,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    })
    return record


def summarize(records: list[dict]) -> dict:
    summary: dict = {}
    for record in records:
        cell = summary.setdefault(record["role"], {}).setdefault(
            record["arm"],
            {"trials": 0, "errors": 0, "_passed": [], "_tools": [],
             "_tokens": [], "_latency": []})
        cell["trials"] += 1
        if record["error"] is not None:
            cell["errors"] += 1
            continue
        cell["_passed"].append(bool(record["passed"]))
        cell["_tools"].append(record["tool_calls"])
        if record["output_tokens"] is not None:
            cell["_tokens"].append(record["output_tokens"])
        cell["_latency"].append(record["latency_s"])
    for arms in summary.values():
        for cell in arms.values():
            scored = cell.pop("_passed")
            tools_used = cell.pop("_tools")
            tokens = cell.pop("_tokens")
            latency = cell.pop("_latency")
            cell["pass_rate"] = (sum(scored) / len(scored)) if scored else None
            cell["mean_tool_calls"] = (sum(tools_used) / len(tools_used)
                                       if tools_used else None)
            cell["mean_output_tokens"] = (sum(tokens) / len(tokens)
                                          if tokens else None)
            cell["mean_latency_s"] = (sum(latency) / len(latency)
                                      if latency else None)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--roles", default="clarify,triage,drilldown")
    parser.add_argument("--arms", default="a,b")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()
    RESULTS.mkdir(exist_ok=True)

    records = []
    for role in args.roles.split(","):
        scenario_list, runner, scenario_id = ROLES[role]
        for scenario in scenario_list:
            for arm in args.arms.split(","):
                for trial in range(1, args.trials + 1):
                    sid = scenario_id(scenario)
                    error, result, report = None, None, None
                    try:
                        result, report = runner(arm, scenario, args.model)
                    except Exception as exc:  # record loudly, keep going
                        error = f"{type(exc).__name__}: {exc}"
                        print(f"TRIAL FAILED {role}/{arm}/{sid}/t{trial}: "
                              f"{error}")
                    record = _record(role, arm, sid, trial, result, report,
                                     error)
                    records.append(record)
                    out = RESULTS / f"{role}_{arm}_{sid}_t{trial}.json"
                    out.write_text(json.dumps(record, indent=2,
                                              default=str) + "\n")
                    status = ("ERROR" if error else
                              "PASS" if record["passed"] else "FAIL")
                    print(f"{role:9s} {arm} {sid:22s} t{trial} {status}")

    summary = summarize(records)
    (RESULTS / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(f"\n{'role':9s} {'arm':3s} {'pass':>6s} {'tools':>6s} "
          f"{'tokens':>8s} {'lat(s)':>7s} {'err':>4s}")
    for role, arms in summary.items():
        for arm, cell in sorted(arms.items()):
            rate = (f"{cell['pass_rate']:.0%}"
                    if cell["pass_rate"] is not None else "n/a")
            print(f"{role:9s} {arm:3s} {rate:>6s} "
                  f"{cell['mean_tool_calls'] or 0:>6.1f} "
                  f"{cell['mean_output_tokens'] or 0:>8.0f} "
                  f"{cell['mean_latency_s'] or 0:>7.1f} "
                  f"{cell['errors']:>4d}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass, then the full hermetic suite**

Run: `cd experiments/react && python -m pytest tests/ -v`
Expected: all PASS. Then from repo root: `python -m pytest -q` → root suite unchanged/green.

- [ ] **Step 6: Write `README.md`**

```markdown
# ReAct Orchestration Experiment

Local-only playground (spec:
`docs/superpowers/specs/2026-08-13-react-orchestration-experiment-design.md`).
Tests whether a bounded ReAct layer *around* the deterministic quant core
beats today's static behaviors. The quant DAG never executes here — runs are
fixtures reused from `experiments/reflexion/`.

Roles × arms: **clarify** (A = direct `compile_run_spec`, B = agent with
defaults/ask_user/compile_spec + simulated user), **triage** (A = stuffed
error prompt, B = read-only evidence tools), **drilldown** (A = stuffed
workflow JSON, B = fetch-on-demand evidence tools).

## Run

    source ../../.venv/bin/activate
    python bundle.py && python mutate.py     # regenerate fixtures (committed)
    python -m pytest tests/ -v               # hermetic suite
    python run_experiment.py --trials 3      # full matrix (Bedrock: Opus 5)
    python run_experiment.py --roles triage --arms b --trials 1   # slice

`REACT_MODEL_ID` overrides the model (e.g. `us.anthropic.claude-sonnet-4-6`
to measure the deployed interpreter). AWS credentials for Bedrock us-east-1
required for the harness only.

## Read the numbers

`results/summary.json` / printed table: per role×arm — `pass_rate` (oracle),
`mean_tool_calls`, `mean_output_tokens`, `mean_latency_s`, `errors`.
The experiment's claims map to: clarify pass_rate (intent resolution),
triage pass_rate + zero `unbounded_action_claim` violations (bounded triage),
drilldown pass_rate with grounding (faithful fetch-on-demand) vs Arm A
tokens (cost of stuff-everything). Per-trial transcripts (final text, tool
trace, sim-user Q&A, violations) are in `results/{role}_{arm}_{scenario}_t{n}.json`.
```

- [ ] **Step 7: Commit the harness**

```bash
git add experiments/react
git commit -m "feat(experiments): react scenario matrix + A/B harness + README

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 8: Live run (Bedrock, the only non-hermetic step)**

Run from `experiments/react/` with AWS credentials for account 654654592675 / us-east-1:
```bash
python run_experiment.py --trials 3
```
Expected: 96 trial lines (clarify 6×2×3 = 36, triage 5×2×3 = 30, drilldown 5×2×3 = 30), then the summary table. Sanity anchors: clarify arm **a** pass_rate = 33% exactly (deterministic: 2 of 6 scenarios pass, every trial identical); triage/drilldown arm **b** `mean_tool_calls` > 0 and arm **a** = 0; `errors` ideally 0 (Bedrock throttling retries come from boto defaults; a few recorded errors are acceptable, rerun the slice if a whole cell errored). If clarify arm a ≠ 33%, STOP — an oracle or fixture regressed; do not tune prompts to fix it.

- [ ] **Step 9: Commit results + memory note**

```bash
git add -f experiments/react/results/summary.json
git commit -m "docs(experiments): react A/B live results summary

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
(Only `summary.json` is force-added past the gitignore; per-trial transcripts stay local.)

---

## Execution notes

- Tasks 1→9 are strictly ordered (each imports the previous). No parallel execution.
- Task 8's Arm B functions and Task 9 Step 8 are the only Bedrock touchpoints; everything else runs offline.
- If a plan test fails in a way that suggests the *reflexion* fixture shape differs from the mini fixture (e.g. missing `paths_uri`), STOP and surface it — do not edit reflexion files or silently reshape bundles (CLAUDE.md Engineering Discipline #1/#4).
- The hierarchical-delegation experiment (spec'd separately, 08b3127) imports this experiment's components — keep the public interfaces in this plan's "Interfaces" blocks stable.

