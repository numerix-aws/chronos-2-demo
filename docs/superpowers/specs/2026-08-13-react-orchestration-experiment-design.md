# ReAct Orchestration Experiment — Design

**Date:** 2026-08-13
**Status:** Local-only experiment (playground). Never deployed; no changes to the deployed agent, tools, or quant path.
**Location:** `experiments/react/` (new top-level directory, excluded from the main pytest run).
**Companion:** [`2026-08-13-reflexion-critic-experiment-design.md`](2026-08-13-reflexion-critic-experiment-design.md) — the critic checks the prose after the fact; this experiment tests whether a ReAct loop improves the interactions *around* the run.

## 1. Question the experiment answers

Does a bounded ReAct layer **around** the deterministic quant core measurably improve, versus the current static behaviors, and at what token/latency cost:

- **(a) intent resolution before a run** — turning an ambiguous prompt into a correct canonical RunSpec via approved defaults or one focused question;
- **(b) failure triage after a broken run** — naming the exact incomplete step and defect from evidence, read-only;
- **(c) grounded drilldown after a successful run** — answering follow-up questions from fetched evidence instead of a stuffed prompt.

**Design principle: ReAct is for adaptability, not authority.** It never decides the quant execution plan. The deterministic workflow DAG (`agent/runtime/workflow.py`) remains the only thing that runs tools during a quant run, and this experiment never executes it — successful and failed runs are fixtures. The target production architecture this experiment informs is:

```
ReAct clarification / intent routing
  → compile_run_spec
  → deterministic workflow DAG
  → deterministic validators
  → LLM narration
  → optional critic (reflexion experiment)
  → ReAct drilldown for follow-up questions
```

## 2. Shape

Three sub-experiments (roles) sharing one harness, one read-only tool layer, and one trace recorder. All agents are Strands `Agent`s — the same framework as the deployed conversational path, so findings transfer — running `BedrockModel(model_id="us.anthropic.claude-opus-5")`, env-configurable (same Opus 5 constraints as the reflexion experiment: no `temperature`/`top_p`/`top_k`; thinking on by default). The reason→act→observe trace is captured from the Strands event stream (thinking + tool events) and saved per trial.

Every role is a two-arm A/B: **Arm A = current architecture baseline, Arm B = ReAct**, both scored by the same deterministic oracle.

## 3. The three roles

### Role C — Clarification (pre-run)

- **Arm A (baseline):** call `compile_run_spec(prompt)` directly (imported from `src/chronos2_demo/run_spec.py`, dummy provenance injected by the harness). An ambiguous prompt yields the static `Clarification` message and the trial ends unresolved.
- **Arm B (ReAct):** Strands agent with three tools:
  - `get_approved_defaults` — returns the documented default policy (as_of, horizon, book, conditioning);
  - `ask_user` — routes to the simulated user (§4); hard cap **2 questions per trial**;
  - `compile_spec` — wraps the real `compile_run_spec`.
- The agent must end with a compiled RunSpec or a justified escalation, then exits — once the spec compiles, ReAct is done.
- **Ground truth:** each scenario carries a hidden intent (e.g. "COVID window, 1y horizon, full book, no conditioning"). The simulated user answers the agent's questions from that intent — and answers vaguely if asked something the intent does not cover.

### Role T — Triage (post-failure)

- **Arm A (baseline):** the raw error event + broken payload handed to a tool-less narrator (today's behavior analog: a failed run just emits the error event).
- **Arm B (ReAct):** agent with **read-only evidence tools over the fixture bundle**: `list_events`, `get_event`, `get_run_spec`, `get_artifact_manifest`, `get_task_status`, `get_diagnostics`.
- **Boundedness is by construction:** no write, rerun, or mutation tools exist in the environment. The trace records any attempt to call a nonexistent tool as a boundedness violation (expected count: zero).
- Deliverable: name the exact incomplete step and defect; no confident quantitative claims from the broken run; only bounded next-step suggestions (no "I reran it with different inputs").

### Role D — Drilldown (post-success)

- **Arm A (baseline):** today's interpretation stage — the full workflow JSON stuffed into a tool-less prompt together with the follow-up question.
- **Arm B (ReAct):** agent with the same read-only evidence tool layer as Role T, fetching only what it needs to answer.
- **Hypothesis under test:** fetch-on-demand is cheaper *and* no less faithful than stuff-everything. The reflexion oracle scores faithfulness for both arms; the trace shows whether every cited number appeared in a fetched observation.

## 4. Simulated user (Role C only)

A small LLM (same model, separate system prompt) holding the scenario's hidden intent. It answers the agent's clarifying questions from the intent, deliberately vaguely when asked about fields the intent leaves open, and never volunteers unasked information. This keeps the dialogue realistic while the oracle still scores the final RunSpec against the hidden intent. Sim-user transcripts are saved with the trial trace.

## 5. Fixtures

Run fixtures are **read directly from `experiments/reflexion/fixtures/`** (read-only cross-reference; no copies to drift). New fixtures live under `experiments/react/fixtures/`.

| Role | Fixtures |
|---|---|
| Clarification | 6 prompt scenarios, each `{prompt, hidden_intent, expected_posture}` JSON: fully-specified; one-field-missing; vague ("run stress scenario"); hopelessly vague ("so, numbers?"); misleading premise ("rerun with Chronos as the pricing engine" — correct behavior corrects the premise, per the demo narrative "Chronos-2 augments, not replaces"); what-if conditioning prompt |
| Triage | Reflexion mutations `missing_exposure.json`, `id_mismatch.json`, `partial_events.json`, plus **two new mutations** (built with the reflexion `mutate.py` pattern): `poll_timeout.json` (check_chronos2 attempts exhausted, `task_status=RUNNING`, no ready artifact) and `hash_mismatch.json` (artifact sha256 disagrees with the manifest). Each fixture carries a labeled ground-truth defect + the step where the run became invalid |
| Drilldown | Reflexion `happy_path.json` and `conditional_whatif.json`, with ~5 follow-up questions spanning exposure deltas, `w_stress` attribution, coverage/tail diagnostics, and provenance |

## 6. Oracles (deterministic; the only unit-tested components)

- **Clarification oracle:** compares the compiled canonical RunSpec field-by-field against the hidden intent (`spec_hash` equality against the expected compile is the strong form). Counts questions asked. Violation types: *asked-while-not-blocked* (approved defaults would have satisfied the intent) and *guessed-while-blocked* (a field the intent fixes but neither prompt nor defaults could supply). Misleading-premise scenario: pass requires correcting the premise; compiling the false premise is a fail.
- **Triage oracle:** defect-identification match against the fixture's ground-truth label (structured/keyword match on step + defect type); reuses the reflexion validator's **run-validity gate** to fail confident quantitative claims from a broken run; scans the trace for boundedness violations.
- **Drilldown oracle:** the reflexion `validator.py` imported as-is for numeric faithfulness and invented values, plus one new check — **evidence grounding**: every number cited in the answer must appear in a tool observation recorded in the trace. (Arm A trivially passes grounding since everything was in-prompt; the metric is whether Arm B stays equally grounded while fetching less.)

## 7. Experiment matrix and scoring

3 roles × 2 arms × scenarios (6 clarification + 5 triage + 5 drilldown) × N trials (default 3; configurable) ≈ **96 trials**. Everything is fixture-backed, so trial wall-clock is dominated by model latency.

**Scoring dimensions:**

1. Task success per role oracle (spec correctness / defect named / faithful answer)
2. Interaction discipline (questions asked; asked-only-when-blocked rate)
3. Boundedness (triage violation count; expect zero by construction)
4. Evidence grounding and invented-value rate
5. Cost: tool calls, loop iterations, tokens, wall-clock per trial — Arm A vs Arm B per role
6. Trace quality: full reason/act/observe transcripts saved to `results/` for human spot-check

Output: `results/*.json` (metrics + full transcripts + sim-user dialogues) plus a printed summary table; `README.md` explains how to read the numbers.

## 8. Components (all under `experiments/react/`)

| Component | File | Description |
|---|---|---|
| Read-only evidence tools | `tools.py` | Fixture-backed Strands tools (`list_events`, `get_event`, `get_run_spec`, `get_artifact_manifest`, `get_task_status`, `get_diagnostics`) shared by Roles T and D |
| Clarification tools | `clarify_tools.py` | `get_approved_defaults`, `ask_user`, `compile_spec` (wraps the real `compile_run_spec`) |
| Simulated user | `sim_user.py` | Hidden-intent answerer (§4) |
| Trace recorder | `trace.py` | Captures reason/act/observe from the Strands event stream; records nonexistent-tool attempts |
| Oracles | `oracles/clarify.py`, `oracles/triage.py`, `oracles/drilldown.py` | Deterministic scoring (§6); drilldown imports the reflexion validator |
| Fixture mutations | `mutate.py` | Builds `poll_timeout.json` and `hash_mismatch.json` from the reflexion capture |
| Harness | `run_experiment.py` | Runs the role × arm × scenario × trial matrix, oracle-scores everything, writes `results/` |

## 9. Error handling & testing

Deliberately minimal — this is an experiment. Bedrock throttling gets boto retries; anything else fails the trial loudly and is recorded as a failed trial. Oracles get hermetic unit tests (feed them traces/outputs with known violations); each agent path and the harness get a smoke test. No live network calls in the repo's main test suite; experiment tests live under `experiments/react/tests/` and are excluded from root `pytest`.

## 10. Out of scope (YAGNI)

No deployment path, no UI, no changes to the production runtime or conversational path, no wrapper `run_quantitative_workflow(spec)` tool (that is the production shape this experiment informs, but here the DAG never executes), no multi-model tournament, no hierarchical delegation (a later playground experiment). If ReAct earns its cost in a role, productionizing that role is a separate plan.

## 11. Cost estimate

~96 trials × (1 agent run + up to 2 sim-user turns) on Opus 5, plus oracle runs (free, deterministic). Same order as the reflexion experiment: a few dollars per full matrix run.
