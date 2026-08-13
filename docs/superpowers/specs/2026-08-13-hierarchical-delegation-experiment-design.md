# Hierarchical Delegation Experiment (Demo Director) — Design

**Date:** 2026-08-13
**Status:** Local-only experiment (playground). Never deployed; no changes to the deployed agent, tools, or quant path.
**Location:** `experiments/hierarchical/` (new top-level directory, excluded from the main pytest run).
**Companions:** [`2026-08-13-reflexion-critic-experiment-design.md`](2026-08-13-reflexion-critic-experiment-design.md) (narrator + critic gate), [`2026-08-13-react-orchestration-experiment-design.md`](2026-08-13-react-orchestration-experiment-design.md) (clarifier, triage, and Q&A specialist bodies).
**Build order:** third — reflexion → react → hierarchical. This experiment reuses ReAct's tools, sim-user, and oracles as specialist internals and reflexion's generator/validator/critic as the narration gate. Do not inline copies; implement ReAct first.

## 1. Question the experiment answers

Does a **hierarchical control plane** — a coded state machine with LLM judgment only at the edges, delegating to tool-scoped specialists — measurably beat a **monolithic do-everything agent** on scripted multi-turn demo sessions, and at what token/latency cost? Four properties the hierarchy enforces by construction and the monolith can only approximate:

1. **Routing** — each turn handled by the right specialist for the (intent, state) pair.
2. **Boundary discipline** — no agent holds tools outside its route's allowlist; nothing re-runs or mutates the quant pipeline.
3. **State correctness** — active `execution_id`, `spec_hash`, run status, and artifact bundle tracked across turns, so "why did PFE move?" after a failed run gets a refusal, not a hallucinated number.
4. **Publication gating** — narration reaches the user only after the deterministic validator + LLM critic pass.

**Design principle: even the manager has no authority.** Reflexion and ReAct put LLM adaptability *around* the deterministic quant core. Here the top of the hierarchy is also deauthorized: the **Demo Director** is a coded state machine (like `workflow.py` is for the DAG), and its LLM does exactly two jobs — fuzzy intent classification and user-facing connective language (refusals, redirects, clarification relay). Sequencing, permission boundaries, state, and publish/block decisions are deterministic code. The Director decides *whether* a specialist's output publishes, never *what* it says.

The target production shape this experiment informs:

```
Demo Director (coded control plane, LLM intent routing)
  → RunSpec clarifier → compile_run_spec
  → deterministic workflow DAG → deterministic validators
  → narrator → critic gate → publish
  → Q&A / triage specialists for follow-ups and failures
```

## 2. Architecture

```
            user turn (from scripted session)
                     │
             ┌───────▼────────┐
             │  Demo Director │  director.py — coded state machine
             │  ┌───────────┐ │  state: {execution_id, spec_hash, run_status,
             │  │ intent LLM│ │   bundle, critic_verdict, diagnostics_ok}
             │  └───────────┘ │  (intent, state) → route is a code table
             └───┬──┬──┬──┬───┘
   quant_run/    │  │  │  │ out_of_scope / general_chat
   what_if       │  │  │  └────────► Director answers directly (no tools;
                 │  │  │              polite redirect — its only prose duty)
                 ▼  │  │
          Clarifier │  │ followup_qa (run_status = complete)
   (ReAct Role C)   │  └──────────► Q&A specialist (ReAct Role D tools,
                 │  │                scoped to the active bundle)
                 │  │ failure_help (run_status = failed)
                 ▼  └─────────────► Triage (ReAct Role T tools,
        compiled RunSpec             scoped to the failure bundle)
                 │                  (followup_qa while failed → refusal, not Q&A)
                 │
        [fixture DAG] — harness resolves spec → success/failure bundle;
                 │       Director state updates (the only "execution")
                 ▼
             Narrator (reflexion generator)
                 │
             Critic gate (reflexion validator + LLM critic, loop.py max-3)
                 │
        pass → publish verbatim     fail after retries → degraded path (§3)
```

- **Intent classifier:** one schema-forced LLM call per turn → `{quant_run, what_if, followup_qa, failure_help, out_of_scope, general_chat}` + confidence. The route is then a coded `(intent, state)` table — e.g. `followup_qa` with no completed run routes to a refusal, not to Q&A.
- **Specialists publish verbatim** once their gate passes; the Director LLM never rewrites specialist output.
- **Boundaries are physical:** each specialist is constructed with only its allowlisted tools, so out-of-boundary calls are impossible by construction. The trace still records any nonexistent-tool attempt (ReAct convention; expected count zero).
- **Models:** all LLM roles are Strands `Agent`s on `BedrockModel(model_id="us.anthropic.claude-opus-5")`, env-configurable, same Opus 5 constraints as the companion experiments (no `temperature`/`top_p`/`top_k`; thinking on by default).

### Arm A — monolithic baseline

One Strands agent per session turn: the **union of all specialist tools** attached (clarify tools + read-only evidence tools), the full result bundle and running session transcript stuffed in-prompt, and one system prompt covering every duty (clarify, narrate, caveat, triage, refuse). No router, no state machine, no critic gate — session state exists only implicitly in the transcript. Same fixtures, same oracles.

### Arm B — Demo Director hierarchy

As diagrammed. State machine in code; intent LLM at the edge; tool-scoped specialists; critic-gated publication.

## 3. Degraded-output ownership

When the critic gate fails after max retries, the Director must not become a quiet narrator. Ownership is explicit:

1. **Narrator degraded mode:** the Director re-invokes the Narrator with the validator's violation list and a constrained instruction — caveat-first, acknowledge the defect, no numeric claim that the validator did not verify. This degraded narration must itself pass the validator's run-validity gate (no confident claims) before publishing.
2. **Coded template fallback:** if the degraded narration also fails, the Director publishes a deterministic template — defect type, `execution_id`, violation count, pointer to the structured artifacts. Pure code, no LLM prose.

The same two-step path handles degraded fixtures (e.g. `hash_mismatch`): the validator blocks the confident narration, the degraded mode produces the caveated partial answer, and the template is the floor.

## 4. Specialists (all reuse; no new agent bodies)

| Route | Specialist | Reused from |
|---|---|---|
| `quant_run` / `what_if` | Clarifier — `get_approved_defaults`, `ask_user` (sim-user), `compile_spec` | ReAct Role C (`clarify_tools.py`, `sim_user.py`) |
| run complete → narrate | Narrator | reflexion `generator.py` |
| publication gate | Validator + LLM critic loop | reflexion `validator.py`, `critic.py`, `loop.py` |
| `followup_qa` | Q&A over the active bundle | ReAct Role D (read-only `tools.py`) |
| `failure_help` / failed run | Triage over the failure bundle | ReAct Role T (read-only `tools.py`) |
| `out_of_scope` / `general_chat` | Director direct answer (no tools) | — |

Explicitly **not** built: per-DAG-step agents (no "baseline agent", "blend agent", etc. — the hardcoded load → run → poll → blend → price workflow remains the only execution authority) and no reporting agent (deferred; see §10).

## 5. Fixtures and scenarios

Run fixtures are read directly from `experiments/reflexion/fixtures/` and `experiments/react/fixtures/` (read-only cross-reference; no copies). New fixtures are **session scripts** under `experiments/hierarchical/fixtures/sessions/`: each is a fixed 2–4 turn script where every turn carries ground truth `{expected_intent, expected_route, expected_state_after, answer_oracle_ref}`.

Eight sessions:

| # | Session | Turns exercise |
|---|---|---|
| 1 | Clean run + drilldown | quant run → gated narration → "why did PFE move?" (Q&A) → "can you deploy this to prod?" (out-of-scope redirect) |
| 2 | Vague quant request | "run stress scenario" → Clarifier asks (sim-user answers from hidden intent) → compile → run → narrate |
| 3 | Conditional what-if | conditional run → narrate → drilldown on `w_stress` attribution |
| 4 | Mid-session failure | run resolves to `poll_timeout` → "what happened?" (triage) → "so what's the PFE?" (refusal: no completed run in state) |
| 5 | Q&A with no run | session opens "why did augmented PFE move?" → refusal/clarify — nothing to explain yet |
| 6 | Misleading premise | run → "now that Chronos-2 replaced the MC engine…" → premise corrected (augments-not-replaces narrative) |
| 7 | Degraded publish | run resolves to `hash_mismatch` → critic blocks → degraded path (§3) exercised end-to-end |
| 8 | Chat/quant mix | greeting + general chat turn (direct answer, no tools) → quant run turn routes correctly |

The **fixture DAG** is the harness resolving a compiled RunSpec to a pre-labeled bundle (success or scripted failure) and updating Director state — the deterministic workflow never executes.

## 6. Oracles (deterministic; the only unit-tested components alongside the Director state machine)

- **Routing oracle (new):** per-turn `(intent, route)` vs ground truth. Splits errors into *intent errors* (LLM misclassified) and *table errors* (code bug — should be zero). Arm B only; the monolith has no route to score.
- **State oracle (new):** Director state after each turn vs `expected_state_after`. Arm B only.
- **Boundary metric:** Arm B — nonexistent-tool attempts (zero by construction). Arm A — count of tool calls outside the ground-truth route's allowlist for that turn. This asymmetry is a headline number.
- **Publication-gate metric:** rate of published answers carrying oracle violations. Arm B expects ~0 (the gate exists); Arm A has no gate — this is the cross-arm faithfulness comparison.
- **Answer oracles (imported):** reflexion `validator.py` for narration/Q&A numeric faithfulness, invented values, and the run-validity gate; ReAct triage oracle for defect identification; ReAct clarification oracle for compiled-spec-vs-hidden-intent; a refusal check for out-of-scope and no-run turns (no fabricated engagement, no numbers).
- **Cost:** LLM calls, tokens, wall-clock per session, per arm.

## 7. Experiment matrix and scoring

2 arms × 8 sessions × N trials (default 3; configurable) = **48 session runs**, ~150 turns total. Cross-arm comparison happens on outcome metrics (publication-gate violations, answer-oracle scores, boundary counts, refusal correctness, cost); routing and state accuracy are Arm-B internal diagnostics that explain *why* outcomes differ.

Output: `results/*.json` (per-turn metrics + full transcripts + Director state trajectories + sim-user dialogues) plus a printed summary table; `README.md` explains how to read the numbers.

## 8. Components (all under `experiments/hierarchical/`)

| Component | File | Description |
|---|---|---|
| Demo Director | `director.py` | Coded state machine: session state, `(intent, state)` → route table, publication gating, degraded path (§3). Unit-tested with stubbed intents — it is pure code. |
| Intent classifier | `intents.py` | Schema-forced single LLM call → intent + confidence |
| Specialist wrappers | `specialists.py` | Thin adapters constructing each reused agent with only its allowlisted tools |
| Monolith baseline | `monolith.py` | Arm A agent (all tools, stuffed context, one prompt) |
| Session fixtures | `fixtures/sessions/*.json` | Eight scripted sessions with per-turn ground truth (§5) |
| New oracles | `oracles/routing.py`, `oracles/state.py`, `oracles/refusal.py` | §6; answer oracles imported from reflexion/react |
| Harness | `run_experiment.py` | Runs arm × session × trial, resolves fixture DAG, oracle-scores every turn, writes `results/` |

## 9. Error handling & testing

Deliberately minimal — this is an experiment. Bedrock throttling gets boto retries; anything else fails the session loudly and is recorded as a failed trial. Hermetic unit tests for the Director state machine and the new oracles (feed them turn traces with known violations); smoke tests for the harness and each route. No live network calls in the repo's main test suite; experiment tests live under `experiments/hierarchical/tests/` and are excluded from root `pytest`.

## 10. Out of scope (YAGNI)

No deployment path, no UI, no real DAG execution, no free-form sim-user sessions (scripts only; the sim-user answers Clarifier questions *within* a turn), no reporting agent (run summaries / talking points / handoff notes from the immutable bundle — a natural v2 specialist once chained delegation is proven), no multi-model tournament, no changes to the production runtime. If the hierarchy earns its cost, productionizing the Director is a separate plan.

## 11. Cost estimate

~48 session runs × 2–4 turns, each turn 1 intent call + 1 specialist run (+ critic loop on narration turns, + up to 2 sim-user turns on clarification turns) on Opus 5. Same order as the companion experiments: low tens of dollars for a full matrix run.

## 12. Known weak points

- Scripted sessions can't measure how the Director handles genuinely off-script user behavior; the out-of-scope and misleading-premise turns are the only adversarial probes. Acceptable for a learning experiment.
- Arm A's boundary metric depends on mapping its free-form behavior onto ground-truth allowlists per turn; borderline calls (e.g. Q&A tools during a clarification turn) are scored against the labeled route, which may slightly overcount violations. Mismatches surface in saved transcripts.
- Routing accuracy is only as meaningful as the intent taxonomy; six classes were chosen to mirror the production Demo Director sketch, not tuned.
