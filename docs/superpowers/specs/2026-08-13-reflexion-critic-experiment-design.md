# Reflexion Critic Experiment — Design

**Date:** 2026-08-13
**Status:** Local-only experiment (playground). Never deployed; no changes to the deployed agent, tools, or quant path.
**Location:** `experiments/reflexion/` (new top-level directory, excluded from the main pytest run).

## 1. Question the experiment answers

Does a two-layer critic (deterministic validator + LLM critic) measurably improve the **faithfulness of the agent's prose explanation to the actual run artifacts** — and at what token/latency cost?

The experiment tests whether the agent's *explanation* of a Chronos-2 run is faithful to the structured ground truth (`run_spec`, `exposure_result`, diagnostics, artifact hashes, scenario roles, `PathSet` provenance). It does **not** test whether Chronos-2 forecasts better — that is measured by the quant pipeline itself.

This extends the existing design direction in
[`2026-07-21-reproducible-quant-execution-design.md`](2026-07-21-reproducible-quant-execution-design.md): *"Model prose may interpret the run but is not an authoritative numerical channel."* The structured events are authoritative; the experiment measures how often the prose drifts from them and whether a critic pass closes the gap.

## 2. What the critic is for

1. **Catching numerical overclaims** — e.g. the narration says "Chronos-2 improved PFE" when the structured metrics show lower PFE, worse coverage, or unavailable diagnostics.
2. **Catching workflow mistakes** — missing `run_spec`, only two exposure results instead of the baseline / chronos-only / augmented triple, mismatched `execution_id`, wrong `spec_hash`, stale or absent artifact URIs.
3. **Protecting the demo narrative** — the project's story is "Chronos-2 augments, not replaces, Monte Carlo" (`AGENTS.md` §Project intent). Flag answers that imply Chronos-2 is the pricing engine, replaces the Numerix-style exposure machinery, or sees the same inputs as the baseline (the asymmetric-covariate story is deliberate).
4. **Defending the quant Q&A** — force the narration to ground itself in coverage, tail dependence, distribution sanity, `w_stress`, and provenance instead of hand-waving. V1 diagnostics defend the headline, not a full model-risk validation package; the narration must not overstate them.
5. **Run-validity gating** — given the earlier malformed-SSE / `JSONDecodeError` incident: are all required events present and parseable, and did the final answer depend only on complete events? The critic doesn't fix a corrupted run, but it stops the agent from confidently explaining one.

## 3. Architecture

Not "ask the same model to think again." Deterministic checks handle everything mechanically checkable (numbers, hashes, IDs, roles, event completeness); the LLM critic handles only semantic issues (overclaiming, narrative violations, missing caveats).

```
fixture (workflow JSON + event stream)
        │
        ▼
  generator ──► narration ──► Layer 1: deterministic validator (oracle)
                                 │  numeric claims, structure, run validity
                                 ▼
                              Layer 2: LLM critic
                                 │  overclaims, narrative, caveats
                                 ▼
                    pass ──► done          fail ──► regenerate with violations
                                                    as feedback (max 3 loops)
```

### Components (all under `experiments/reflexion/`)

| Component | File | Description |
|---|---|---|
| Fixtures | `fixtures/*.json` | One real captured run + deterministic mutations (see §4). Capture script pulls structured results of a past run from S3 (`runs/{execution_id}/…`), committed once; experiments are hermetic on the data side afterward. |
| Generator | `generator.py` | Replicates the production interpretation stage: tool-less Strands `Agent`, production `system_prompt.md`, the same "interpret these structured results without changing any value" prompt template from `agent/runtime/agent.py`. |
| Validator (oracle) | `validator.py` | Deterministic, non-LLM. See §5. The only component with real unit tests. |
| LLM critic | `critic.py` | Schema-forced verdict `{pass, violations: [{type, claim, evidence}]}` given narration + fixture. Prompted for the semantic checks in §2 items 1, 3, 4. |
| Reflexion loop | `loop.py` | generate → validate → critique → if fail, regenerate with violation feedback → repeat, max 3 iterations. |
| Harness | `run_experiment.py` | Runs the scenario × arm matrix (§6), oracle-scores every narration in both arms, writes metrics + transcripts to `results/`. |

### Models

Generator and critic both run Strands `BedrockModel(model_id="us.anthropic.claude-opus-5")` — verified available as a cross-region inference profile in the account (us-east-1). Model ID configurable via env var (e.g. rerun with `us.anthropic.claude-sonnet-4-6` to measure the deployed interpreter, or a cheaper critic model).

Opus 5 constraints honored: no `temperature`/`top_p`/`top_k` (removed — 400 on Opus 5); thinking is on by default. Variance across trials comes from natural sampling; if baseline variance is too low for the critic to have anything to catch, fall back to mild per-trial prompt perturbation.

**Framing caveat:** with Opus 5 in both arms, Arm A is *not* "today's production behavior" (production interprets with Sonnet 4.6). The experiment is a controlled single-pass vs. reflexion comparison on Opus 5; the Sonnet re-run is a one-env-var follow-up.

## 4. Fixtures

One real capture plus deterministic mutations of it (mutations keep the experiment hermetic and give the validator known-bad inputs):

| Fixture | Source | Correct narration behavior |
|---|---|---|
| `happy_path.json` | Captured from a real past run | Full interpretation; all three exposure results cited correctly |
| `conditional_whatif.json` | Captured from a real conditional run (e.g. the 2026-08-06 what-if) | Interprets `chronos2_conditional` source + conditioning correctly |
| `missing_exposure.json` | Mutation: `chronos_only` result deleted | Must acknowledge the missing result, not narrate around it |
| `id_mismatch.json` | Mutation: corrupted `spec_hash` on one result | Must flag inconsistent provenance, not blend the numbers |
| `partial_events.json` | Mutation: truncated / unparseable event in the stream | Run-validity gate: must not confidently report numbers from an incomplete run |

## 5. Layer 1 — deterministic validator (the oracle)

Non-LLM, fully unit-tested, scenario-aware. Checks a narration against its fixture:

- **Numeric claims:** parse dollar amounts, percentages, and dates out of the narration; normalize units ($6.63M ≡ 6,630,000); match with 0.5% relative tolerance against expected values computed from the fixture — terminal EE / PFE 97.5% / ES 97.5% for all three exposure sets, the PFE delta %, `w_stress`, coverage diagnostics, as-of date. Violation types: *wrong value* (contradicts fixture) and *invented value* (no counterpart in fixture).
- **Structural claims:** `run_spec` present; exactly three exposure results with the canonical source→role mapping (`parametric`→`baseline`, `chronos2`/`chronos2_conditional`→`chronos_only`, `blended`→`augmented`); `execution_id` and `spec_hash` consistent across everything the narration references; artifact URIs and sha256s present.
- **Run-validity gate (degraded fixtures):** for the mutation fixtures, confident quantitative claims are violations by construction — the correct narration acknowledges the defect. The oracle knows each fixture's expected posture.

The oracle serves double duty: it is the reflexion loop's Layer 1 **and** the impartial scorer of both arms — which is what lets us measure whether the LLM critic is actually a good judge (critic precision/recall vs. oracle on the mechanically checkable subset).

## 6. Experiment matrix

Two arms × five scenarios × N trials (default 5 per cell; configurable):

- **Arm A — single pass:** generator only (current architecture: one narration, no check).
- **Arm B — reflexion:** full two-layer loop from §3.

Scenario → fixture mapping:

| Scenario | Fixture | Prompt |
|---|---|---|
| Happy path | `happy_path.json` | Standard headline-demo interpretation request |
| Conditioned what-if | `conditional_whatif.json` | Standard interpretation request |
| Ambiguous | `happy_path.json` | Vague prompt ("so how did it go?") — narration must stay grounded without a precise ask |
| Failed tool | `missing_exposure.json`, `id_mismatch.json`, `partial_events.json` | Standard request against degraded data — must acknowledge the defect |
| Intentionally misleading | `happy_path.json` | Prompt asserts something false ("explain how Chronos-2 replaced the Monte Carlo engine") — correct behavior is to correct the premise |

**Scoring dimensions** (every narration in both arms, oracle-scored; semantic dimensions from critic verdicts + saved transcripts for human spot-check):

1. Factual faithfulness (oracle violation rate, by type)
2. Correct labels (scenario roles / sources)
3. Artifact grounding (IDs, hashes, URIs referenced correctly)
4. No fabricated numbers (invented-value rate)
5. Useful caveats (degraded runs acknowledged; diagnostics limits stated)
6. Cost: iterations-to-converge, tokens per trial, wall-clock latency per trial
7. Critic quality: precision/recall vs. oracle on the checkable subset

Output: `results/*.json` (metrics + full transcripts) plus a printed summary table; `README.md` explains how to read the numbers.

## 7. Error handling & testing

Deliberately minimal — this is an experiment. Bedrock throttling gets boto retries; anything else fails the trial loudly and is recorded as a failed trial. Oracle gets hermetic unit tests (feed it narrations with known violations); generator/critic/loop get a smoke test each. No live network calls in the repo's main test suite; experiment tests live under `experiments/reflexion/tests/` and are excluded from root `pytest`.

## 8. Out of scope (YAGNI)

No deployment path, no UI, no session persistence, no multi-model tournament, no changes to the conversational or quant paths, no wiring the critic into the live runtime. If the experiment shows the critic earns its cost, productionizing it is a separate plan.

## 9. Cost estimate

Opus 5 on Bedrock ≈ $5/$25 per Mtok. Arm B worst case ≈ 7 calls/trial; 50 trials across the matrix with few-KB fixtures per prompt → low tens of dollars for a full run.

## 10. Known weak points

- Regex-based claim extraction will miss oddly phrased numbers; tolerance matching plus the invented-value rule covers most cases, and mismatches surface in saved transcripts.
- Semantic dimensions (narrative protection, caveat quality) have no deterministic ground truth — critic-only, so those results are directional and rely on transcript spot-checks.
- Single-fixture-per-scenario means results are conditioned on those specific runs; acceptable for a learning experiment.
