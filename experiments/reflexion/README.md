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
