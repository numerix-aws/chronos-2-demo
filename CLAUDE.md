# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

This repo is **docs-only as of 2026-05-22**. The source of truth is two artefacts under `docs/superpowers/`:

- `specs/2026-05-22-numerix-chronos2-poc-design.md` — approved design spec
- `plans/2026-05-22-plan-a-quant-pipeline*.md` — Plan A, split across 8 files (`*.md`, `*-part-2a..2d.md`, `*-part-3a..3c.md`), 30 tasks across 9 stages

When the user asks about implementation details, **read the plan files first**. They contain the complete, copy-pasteable code for every module — including failing tests, expected pytest output, and commit messages. Don't reinvent. Don't paraphrase. Plan A part-1 has the locked-in file-structure tree (`src/chronos2_demo/...`) — follow it exactly.

A second plan ("Plan B — UX") covering the AgentCore copilot, Lambda tools, API Gateway, and Cloudscape SPA is **not yet written**. Items legitimately deferred to Plan B: §5 Curated Knowledge, §7 Agent Behavior & Tool Surface, §10 Adjacent use case briefs, S3 helper utilities, operational latency metrics.

## Project intent

Proof-of-concept for **Numerix** showing how **Amazon Chronos-2** augments (does not replace) their hybrid Monte Carlo framework for PFE/XVA exposure calculation. The headline beat is "correct + reweight": parametric MC and Chronos-2 both produce path sets, a deterministic regime detector emits `w_stress ∈ [0,1]`, and the blender importance-weights paths so the same downstream pricing/exposure code consumes either set. Plan A delivers the Python core + a Jupyter notebook that drives the demo story end-to-end. Plan B will wrap it in the agent + UI.

## Plan-execution conventions

Before executing any task, read the **"Executor's Contract"** section near the top of `docs/superpowers/plans/2026-05-22-plan-a-quant-pipeline.md`. It applies the Karpathy guidelines (think first, simplicity, surgical changes, verify don't trust) to this plan specifically — most importantly, **don't add code beyond what the task shows**, and **stop and ask** if the plan and reality disagree rather than silently rewriting.

Plan A enforces a rigid per-task workflow that future Claude instances must preserve when executing tasks:

1. **5-step TDD pattern per task**: write failing test → run, confirm fail → implement minimal code → run, confirm pass → commit. Each step is a checkbox in the plan; tick them in order, never batch.
2. **One commit per task** with the message exactly as written in the plan, including the `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` trailer.
3. **Tests are hermetic**. Network and SageMaker calls are mocked; matplotlib uses `Agg`; the `PathSet` dataclass and shared fixtures live in `tests/conftest.py`. Don't introduce live network calls into the test suite.
4. **Pinned numbers** (Task 29) — the headline PFE delta is computed once from a frozen synthetic panel under fixed seeds and asserted with a regression test. Keep `tests/fixtures/headline_panel.parquet` checked in (it bypasses the `data/` gitignore via a `!tests/fixtures/` exception).
5. **No covariates in the parametric baseline.** That asymmetry (Chronos-2 sees VIX/MOVE/WTI; baseline doesn't) is part of the value story, not a bug.

If a task has no failing test (Stage 0 bootstrap), the plan says so — follow what's written, not the general TDD shape.

## Module layout (planned)

The plan locks in this structure under `src/chronos2_demo/` — each subdirectory is one responsibility:

- `data/` — fetchers, alignment, covariates, regime labels
- `models/baseline_mc.py` — PCA + Hull-White + GBM joint sampler (Stage 2)
- `models/chronos2_client.py` — SageMaker endpoint wrapper (Stage 3)
- `augmentation/regime_detector.py` + `augmentation/blender.py` — Stage 4 augmentation layer
- `pricing/` — XCCY book + valuation + EE/PFE/ES (Stage 5)
- `diagnostics/` — coverage, tail dependence, distribution distance (Stage 6)
- `plotting/` — thin matplotlib helpers, return `Figure` objects (Stage 7)
- `infra/sagemaker_endpoint.py` — endpoint deploy/teardown (Stage 3)

Tests mirror this tree under `tests/`. The `PathSet` dataclass (Task 7 territory) — `paths: ndarray (n_paths, horizon, n_series)`, `weights`, `series`, `dates`, `source` — is the shared contract between engines, blender, pricing, and diagnostics. **Don't change its shape without updating every consumer.**

## Once code exists (Stage 0 onward)

```bash
# bootstrap (Task 1)
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
