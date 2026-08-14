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
`mean_tool_calls`, `mean_output_tokens`, `mean_latency_s`, `errors`, and
`violation_types` (per-cell violation counts, cells scored since oracle v2).
The experiment's claims map to: clarify pass_rate (intent resolution),
triage pass_rate + zero `unbounded_action_claim` violations (bounded triage),
drilldown pass_rate with grounding (faithful fetch-on-demand) vs Arm A
tokens (cost of stuff-everything). Per-trial transcripts (final text, tool
trace, sim-user Q&A, violations) are in `results/{role}_{arm}_{scenario}_t{n}.json`.
Partial-role reruns (`--roles drilldown`) merge into the existing
`summary.json` instead of overwriting it; the committed summary mixes the
2026-08-13 clarify/triage cells with the 2026-08-14 drilldown rerun (oracle
v2).

## Known limitations

The drilldown faithfulness oracle (v2, `oracles/drilldown.py`) accepts any
numeric payload leaf, bounded derived percent-changes/ratios over headline
scalars at tight tolerance, absolute-value citations of negative deltas, and
round-to-integer citations — so a claim derived from exposure-*series*
arithmetic can still flag `wrong_value` (1 such borderline case in the
2026-08-13 transcripts). Deterministic verification of arbitrary derived
arithmetic is deliberately out of scope: widening further would make the
check vacuous. Trace records successful tool calls only (boundedness is by
construction plus a text check), and triage arm A's pass rate excludes 3
MaxTokens-errored trials (3/15) — the stuffed-prompt baseline's own failure
mode.
