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

## Known limitations

Drilldown `pass_rate` in the committed `results/summary.json` (0% both arms, 2026-08-13 run) is NOT interpretable as an arm comparison: the reflexion validator reused as the faithfulness oracle only knows exposure terminal values, the PFE delta, and w_stress, so real diagnostics-attribution percentages and the literal "97.5%" quantile label are flagged `invented_value` (198 violations), and truncated hashes flag `wrong_identifier` (65 violations). An oracle-v2 recalibration is deferred; until then, read drilldown via the per-trial `ungrounded_claim` and `wrong_value` records in `results/`. Trace records successful tool calls only (boundedness is by construction plus a text check), and triage arm A's pass rate excludes 3 MaxTokens-errored trials (3/15).
