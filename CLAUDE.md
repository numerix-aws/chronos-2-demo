# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

**Plan A + Plan B are code-complete on `main` as of 2026-06-04** (96 core tests + 69 tools/agent tests passing). The shipped code is the primary source of truth; the design docs under `docs/superpowers/` remain the authoritative *reference* for intent, task history, and copy-pasteable module code:

- `specs/2026-05-22-numerix-chronos2-poc-design.md` — original design spec (2026-05-22). **Intentionally not updated** after the 2026-06-04 AutoGluon/quantile/Fargate/9-tool re-architecture — see the "spec vs plan" rule below. Treat architectural details here as historical unless they match the code.
- `plans/2026-05-22-plan-a-quant-pipeline*.md` — Plan A (Python core + notebook), 8 files, 30 tasks across 9 stages
- `plans/2026-05-22-plan-b-ux-agent*.md` — Plan B (CDK infra, AgentCore copilot, Cloudscape SPA), 9 files, 26 tasks across 10 stages.

When the user asks about implementation details, **read the shipped code first, then the plan files** — the plans contain the complete, copy-pasteable code for every module (including failing tests, expected pytest output, and commit messages) and explain *why* each piece exists. Don't reinvent. Don't paraphrase. Plan A part-1 and Plan B part-1 each have a locked-in file-structure tree.

**Multi-part plans**: files end with `> _Continue with <next-file>._` — read the whole chain before claiming "the plan says X."

## Project intent

Proof-of-concept for **Numerix** showing how **Amazon Chronos-2** augments (does not replace) their hybrid Monte Carlo framework for PFE/XVA exposure calculation. The headline beat is "correct + reweight": parametric MC and Chronos-2 both produce path sets, a deterministic regime detector emits `w_stress ∈ [0,1]`, and the blender importance-weights paths so the same downstream pricing/exposure code consumes either set. Plan A delivers the Python core + a Jupyter notebook that drives the demo story end-to-end. Plan B will wrap it in the agent + UI.

## Engineering Discipline (project-wide)

These rules apply to **every** change in this repo — plan-driven or not. They distill the Karpathy operating guidelines into project-specific rules. Re-read whenever you're tempted to deviate.

**1. Think before coding.** Read the entire task — files, all steps, the test, the implementation, and the commit message — before touching the keyboard. If a test in a plan looks wrong, an implementation looks wrong, or two tasks contradict each other, **stop and ask the user**. Don't pick silently. Don't paper over confusion with extra code.

**2. Simplicity first — the plan IS the minimum.** When a plan exists, the code blocks have been sized intentionally. Do not add: extra error handling for cases the test doesn't cover, type hints beyond what's shown, abstractions ("strategy", "factory", "manager") for single-use code, configurability that wasn't requested, defensive `try/except` around code that can't fail. If you write more lines than the plan, you're wrong — go back and copy what's written. Project-specific calls: the asymmetric covariate decision (parametric baseline doesn't see VIX/MOVE/WTI) and the "Chronos-2 always runs alongside, never replaces" framing are deliberate; do not "fix" them.

**3. Surgical changes only.** Each task names exactly the files it Creates or Modifies. Don't touch others. Don't reformat existing code. Don't rename a variable in module X because you're working in module Y. Don't delete dead code you happen to notice — flag it in your end-of-task summary instead. The diff for one task should trace, line-by-line, to that task's checkboxes — and nothing else.

**4. Goal-driven execution — verify, don't trust.** Each task's success criteria are objective: the failing test fails, the passing test passes, the commit lands. Don't mark a step done because it "should work." Run the command, read the output, then tick the box. If a test passes on the first run before you've written the implementation, something is wrong — stop and investigate. If the expected pytest output in a plan disagrees with what you see, surface it before continuing.

**Edge case:** if you genuinely believe a plan has a bug (test asserts the wrong thing, implementation can't satisfy the test, a type signature is inconsistent across tasks), do **not** silently rewrite. Pause, name the discrepancy, and ask the user. The plan is the source of truth until they say otherwise.

## Plan-execution conventions

Plan A enforces a rigid per-task workflow that future Claude instances must preserve when executing tasks:

1. **5-step TDD pattern per task**: write failing test → run, confirm fail → implement minimal code → run, confirm pass → commit. Each step is a checkbox in the plan; tick them in order, never batch.
2. **One commit per task** with the message exactly as written in the plan, including the `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` trailer.
3. **Tests are hermetic**. Network and SageMaker/AutoGluon calls are mocked; matplotlib uses `Agg`; the `PathSet` dataclass lives in `src/chronos2_demo/types.py`, and shared fixtures live in `tests/conftest.py`. Don't introduce live network calls into the test suite.
4. **Pinned numbers** (Task 29) — the headline PFE delta is computed once from a frozen synthetic panel under fixed seeds and asserted with a regression test. Keep `tests/fixtures/headline_panel.parquet` checked in (it bypasses the `data/` gitignore via a `!tests/fixtures/` exception).
5. **No covariates in the parametric baseline.** That asymmetry (Chronos-2 sees VIX/MOVE/WTI; baseline doesn't) is part of the value story, not a bug.

If a task has no failing test (Stage 0 bootstrap), the plan says so — follow what's written, not the general TDD shape.

## Plan B architecture invariants (don't "fix" these)

- **Streaming uses a Lambda Function URL with `InvokeMode=RESPONSE_STREAM`**, not API Gateway — REST API GW buffers responses, breaking SSE.
- **Frontend SSE uses `fetch` + `ReadableStream`**, not `EventSource` — EventSource cannot send the `x-api-key` header the authorizer requires.
- **Agent layer is Amazon Bedrock AgentCore** (not classic Bedrock Agents). L1 constructs from `aws-cdk-lib/aws-bedrockagentcore`: `CfnGateway` + `CfnGatewayTarget` (the 9 tools as MCP tools), `CfnRuntime` + `CfnRuntimeEndpoint` (a containerized Strands agent). Invoked via `bedrock-agentcore:InvokeAgentRuntime`. The installed CDK (2.257.0) has **no** `CfnAgentActionGroup`; classic `CfnAgent`+action-groups are deliberately not used. Gateway delivers flat tool-arg events to the Lambdas, so `@bedrock_action` is a pass-through.
- **Chronos-2 is deployed via AutoGluon Cloud, served serverless, and returns QUANTILES — not sample paths.** `models/chronos2_client.py` builds a long-format request DataFrame and reconstructs the joint `(n_paths, horizon, n_series)` PathSet client-side from per-series quantiles (inverse-CDF + lookback Gaussian copula). The endpoint object is injected (`infra.sagemaker_endpoint.open_endpoint`), so the core package/tests never import `autogluon-cloud`.
- **`run_chronos2` is an async Fargate task, not a Lambda** (mirrors `run_baseline_mc`): a thin launcher Lambda (`ecs:RunTask`) + a `check_chronos2` poll Lambda (`ecs:DescribeTasks`), with the AutoGluon SDK bundled in the Fargate image. The chronos2 task role holds `sagemaker:InvokeEndpoint`. Don't "simplify" it back to a Lambda proxy — the AutoGluon dep is too heavy for a Lambda layer.
- **Amplify Hosting uses manual zip deploys** (`aws amplify create-deployment` + curl PUT to `zipUploadUrl` + `start-deployment`), not GitHub source.
- **Sessions table:** PK=`session_id`, SK=`turn_id` (ISO-8601 timestamp + `#role`). Roles: `{user, assistant, tool}`.

## Module layout

The Plan A package lives under `src/chronos2_demo/` — each subdirectory is one responsibility:

- `data/` — fetchers, alignment, covariates, regime labels
- `models/baseline_mc.py` — PCA + Hull-White + GBM joint sampler (Stage 2)
- `models/chronos2_client.py` — Chronos-2 client: AutoGluon endpoint request frame + quantile→joint-path reconstruction (Gaussian copula) (Stage 3)
- `augmentation/regime_detector.py` + `augmentation/blender.py` — Stage 4 augmentation layer
- `pricing/` — XCCY book + valuation + EE/PFE/ES (Stage 5)
- `diagnostics/` — coverage, tail dependence, distribution distance (Stage 6)
- `plotting/` — thin matplotlib helpers, return `Figure` objects (Stage 7)
- `infra/sagemaker_endpoint.py` — Chronos-2 deploy/teardown via AutoGluon Cloud (`deploy_demo_endpoint`/`delete_demo_endpoint`/`open_endpoint`; serverless default) (Stage 3)

Tests mirror this tree under `tests/`. The `PathSet` dataclass (`src/chronos2_demo/types.py`, Task 6 territory) — `paths: ndarray (n_paths, horizon, n_series)`, `weights`, `series`, `dates`, `source` — is the shared contract between engines, blender, pricing, and diagnostics. **Don't change its shape without updating every consumer.**

Plan B wraps that package in these top-level directories (each its own deploy/test surface):

- `agent/` — AgentCore copilot: `action_groups.json` (9 tool schemas), `system_prompt.md`, `runtime/` (containerized Strands agent), `knowledge/` (use-case briefs), `tests/`
- `tools/` — tool implementations: `lambda/` (9 tool handlers + sessions/invoke/sse_relay/authorizer + `shared/`) and `fargate/` (`baseline_mc`, `run_chronos2` async workers); `tests/`
- `infra/` — CDK app (TypeScript): 7 stacks under `lib/` (network, storage, tools, agent, api, frontend, observability) + `test/` jest snapshots
- `frontend/` — Cloudscape React SPA (Vite + vitest + Playwright): chat panel, what-if form, SSE streaming
- `scripts/` — `snapshot_data.py`, `deploy_chronos2_endpoint.py`; `docs/runbook.md` — deploy/demo/teardown runbook

## Commands

```bash
# bootstrap
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# run tests
pytest                                         # full suite
pytest tests/pricing/test_exposure.py -v       # one file
pytest tests/pricing/test_exposure.py::test_pfe_matches_quantile_under_uniform_weights -v   # one test

# headline notebook (Stage 8 deliverable)
jupyter lab notebooks/headline_demo.ipynb
```

`pyproject.toml` (Task 1) configures `pytest` with `testpaths=["tests"]` and `--strict-markers`.

## Working effectively in this repo

- **When asked to implement a task**: read the relevant plan file in full, follow the 5-step pattern, copy the code blocks verbatim. Don't optimize, refactor, or "improve" the code in the plan unless the user asks.
- **When asked to write new code outside the plan**: pause and ask — the plan defines scope. New scope means new task entries, ideally appended to a future plan.
- **When the spec and the plan disagree**: the plan is more recent and detailed; flag the conflict to the user before continuing.
- **Frequent commits**. Plan A has 30 commits planned; don't merge them.
- **Subagent-driven execution** (`superpowers:subagent-driven-development`) is the recommended path for grinding through Plan A — fresh subagent per task, two-stage review between tasks. Inline execution via `superpowers:executing-plans` is the alternative.
- **Cross-cutting rules go here, not in plans.** If a guideline applies to all changes, add it to "Engineering Discipline." Plans reinforce — they don't redefine.
- **ARCC trigger:** Plan B touches IAM, S3, VPC, Lambda, Secrets Manager, API Gateway. Per `~/.claude/rules/arcc-governance.md`, query `search_arcc` BEFORE examining code on each new infra domain (one query per stack is usually enough).
