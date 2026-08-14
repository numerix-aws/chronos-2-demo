# Hierarchical Delegation Experiment

This experiment evaluates a hierarchical agent architecture (Arm B: Director + Specialists) against a monolithic baseline (Arm A) across four core properties:

1. **Intent classification**: Can the Director route user queries correctly?
2. **State tracking**: Does the Director maintain execution state (run status, bundle availability) across turns?
3. **Grounding**: Do both arms produce answers faithful to the retrieved context (execution bundles, clarification fixtures)?
4. **Boundary adherence**: Do specialists stay within their designated tool allowlists?

## Prerequisite

The `experiments/react/` ReAct implementation must be built and tested first. This experiment's `bridge.py` loads the ReAct drilldown oracle for clarification and QA specialist tool implementations.

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

This executes 48 session runs (2 arms × 8 sessions × 3 trials) against live Bedrock endpoints and writes:
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
- If `table_error > 0` (counted in `routing.score_turn`), the route table has entries not covered by test sessions — this is a route-table bug, not a model failure.

**Answer scoring caveat**: The `qa` and `qa_premise` rubrics depend on the ReAct drilldown oracle's extraction correctness. That oracle is being recalibrated separately; live answer pass-rates for QA turns may be artificially low until recalibration completes.

## Cost Expectations

Per-turn costs are dominated by:
- Intent classification: 1 Claude call (~300 tokens in, ~50 out)
- Specialist/monolith answers: 1 Claude call per turn (varies by tool usage; clarify turns may be 2–5K tokens in, 200–500 out; QA turns 3–6K in, 300–800 out)
- Narration generation (Arm B only): 1 Claude call (~1K in, ~200 out) + up to 3 critique/refinement calls if validation fails

A full 3-trial run (48 sessions, ~120 turns total) costs approximately:
- **Arm A (monolith)**: ~60 turns × ~4K tokens avg ≈ 240K tokens in, 40K out
- **Arm B (hierarchical)**: ~60 turns × (300 + 4K + 1K narration) ≈ 300K tokens in, 50K out

At Claude Sonnet pricing (~$3/M in, ~$15/M out), expect **~$2–3 per full run**.

## Experiment Results Location

All `results/experiment_*.json` files are gitignored. Headline metrics are recorded in task summaries and commit messages only.
