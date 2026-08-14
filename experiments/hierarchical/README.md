# Hierarchical Delegation Experiment

This experiment evaluates a hierarchical agent architecture (Arm B: Director + Specialists) against a monolithic baseline (Arm A) across four core properties:

1. **Intent classification**: Can the Director route user queries correctly?
2. **State tracking**: Does the Director maintain execution state (run status, bundle availability) across turns?
3. **Grounding**: Do both arms produce answers faithful to the retrieved context (execution bundles, clarification fixtures)?
4. **Boundary adherence**: Do specialists stay within their designated tool allowlists?

## Prerequisite

The `experiments/react/` ReAct implementation must be built and tested first. This experiment's `bridge.py` loads ReAct's clarify/evidence TOOLS for specialists and ReAct's triage/drilldown/clarify ORACLES for scoring.

## Running the Experiment

### Run Tests

```bash
cd experiments/hierarchical
python -m pytest tests/ -v
```

All 9 test files should pass (hermetic unit tests for sessions, intents, routing, scoring, bridge, specialists, monolith, publication, and the smoke harness).

### Run Harness (Live Bedrock)

From `experiments/hierarchical/`:

```bash
python run_experiment.py --trials 3
```

This executes 48 session runs (2 arms × 8 sessions × 3 trials, ~108 scored turns) against live Bedrock endpoints and writes:
- A `results/experiment_<unix_ts>.json` file with per-turn records and aggregated summary
- A two-row summary table printed to stdout

Optional arguments:
- `--trials N` (default 3): Number of repetitions per arm/session pair
- `--sessions s1 s2 ...` (default all 8): Filter to specific session IDs
- `--model-id <model>` (default from env): Override the Bedrock model ID

## Reading the Summary Table

Each row reports one arm's performance across all turns:

| Metric | Interpretation |
|--------|----------------|
| `intent_accuracy` | Fraction of turns where classified intent matches ground truth (Arm B only; Arm A has no intent classifier) |
| `route_accuracy` | Fraction of turns where Director route matches expected route (Arm B only) |
| `state_accuracy` | Fraction of turns where tracked state (run status, bundle presence) matches expected state (Arm B only) |
| `boundary_violations` | Count of tool calls outside the expected route's allowlist (both arms; Arm B should always be 0 by construction) |
| `answer_pass_rate` | Fraction of turns where the answer passes its scoring rubric (both arms; the cross-arm comparison metric) |
| `publication_channels` | Histogram of narration publication channels (Arm B: `{"narrator": N}`; Arm A: `{}` — monolith has no separate narration step) |
| `mean_latency_s` | Average per-turn wall-clock latency (both arms) |

**Diagnostics**:
- If `route_accuracy < 1.0`, inspect Director routing logic or the route table.
- If `state_accuracy < 1.0`, inspect Director state updates in `apply_outcome`.
- If `boundary_violations > 0` for Arm B, the specialist construction is broken (it hard-wires allowlists, so violations should be impossible).
- If `table_error > 0` (counted in `routing.score_turn`), the intent was classified correctly but the coded route table produced a route different from ground truth — a route-table code bug, not a model failure.

**Answer scoring caveat**: The `qa` and `qa_premise` rubrics depend on the ReAct drilldown oracle's extraction correctness. That oracle is being recalibrated separately; live answer pass-rates for QA turns may be artificially low until recalibration completes.

**Arm A narration caveat**: Arm A (monolith) generates its reply on run turns BEFORE the fixture DAG resolves, so narration-turn scores are not comparable across arms (Arm A can pass vacuously with a number-free reply, and s7's degraded acknowledgement is structurally unavailable to it). Read narration rows per-kind and cross-arm compare on qa/triage/refusal/chat kinds instead.

## Cost Expectations

Per-turn costs are dominated by:
- Intent classification: 1 Claude call (~300 tokens in, ~50 out)
- Specialist/monolith answers: 1 Claude call per turn (varies by tool usage; clarify turns may be 2–5K tokens in, 200–500 out; QA turns 3–6K in, 300–800 out)
- Narration generation (Arm B only): 1 Claude call (~1K in, ~200 out) + up to 3 critique/refinement calls if validation fails

A full 3-trial run (48 sessions, ~108 turns total) costs approximately:
- **Arm A (monolith)**: ~54 turns × ~4K tokens avg ≈ 216K tokens in, 36K out
- **Arm B (hierarchical)**: ~54 turns × (300 + 4K + 1K narration) ≈ 270K tokens in, 45K out

The pinned model is **us.anthropic.claude-opus-5** (~$5/M in, ~$25/M out). Expect **low tens of dollars** per full run.

## Experiment Results Location

All `results/experiment_*.json` files are gitignored (full per-turn transcripts). The headline metrics of each accepted live run are committed in `results/summary.json`.

## Live Results (2026-08-14, drilldown oracle v2)

2 arms × 8 sessions × 3 trials, `us.anthropic.claude-opus-5` (`results/summary.json`):

| Metric | Director (Arm B) | Monolith (Arm A) |
|---|---|---|
| Intent / route / state accuracy | 1.00 / 1.00 / 1.00 | n/a (no routing) |
| Boundary violations | **0** (structural) | 0 |
| Answer pass rate (overall) | **0.98** | 0.65 |
| — narration | 1.00 | 0.33 (not cross-arm comparable, see caveat) |
| — refusal / chat / triage / qa | 1.00 each | 0.67 / 1.00 / 1.00 / 0.92 |
| — qa_premise | 0.50 | 0.67 |
| Clarify pass rate | 1.00 | n/a |
| Publication channels | 11 narrator / 3 degraded / 1 template | — |
| Mean latency per turn | 63.3 s | 33.7 s |
| Failed trials (recorded) | 6 of 24 | 0 of 24 |

Readings: the control plane's structural guarantees all held live (routing, state, boundaries, gated publication — including the degraded→template path firing on the `hash_mismatch` session). The hierarchy's cost is ~2× per-turn latency plus the critic-loop tokens (~1.1M in / ~93k out across narration turns). The 6 failed Director trials are 5 specialist `MaxTokensReachedException`s (8192-token cap on Opus 5 with thinking) and 1 critic structured-output validation error — recorded as failed trials per spec §9, every session retains scored trials. `qa_premise` 0.50 (n=2 scored) is the one weak Director cell; the premise-correction check is strict (requires both "augment" and a not-replace phrase). Raising specialist `max_tokens` is the obvious lever before any rerun.
