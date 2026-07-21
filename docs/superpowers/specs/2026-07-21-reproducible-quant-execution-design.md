# Reproducible Quantitative Execution Design

**Date:** 2026-07-21

## Objective

Make every supported quantitative request reproducible across equivalent natural-language wording, align the live and calibration pipelines, identify scenario results from artifact provenance rather than call order, and measure both Chronos-only contribution and held-out coverage.

The initial live acceptance prompt is:

> Run the stage-safe headline demo for September 30, 2022. Use five years of trading history, project one trading year into the future, and generate 500 scenarios with each engine. Apply a 53.05% stress weight. Show the market regime and compare baseline exposure with Chronos-2-augmented exposure. Report the final EE, 97.5% PFE, 97.5% ES, and the PFE change.

Three independent executions of that request must produce identical cent-level raw metrics and provenance-equivalent inputs.

## Guarantee Boundary

Reproducibility applies to supported, unambiguous quantitative requests. Equivalent dates, units, aliases, and business-language expressions normalize to one immutable run specification. Qualitative requests such as greetings and use-case lookup do not create a run specification.

An ambiguous or unsupported quantitative request fails closed and asks for clarification. The agent must not select a date, horizon, path count, seed, book, stress weight, conditioning target, or conditioning period by best-effort inference when more than one supported interpretation remains.

Reproducibility is defined against pinned input and implementation versions. A deliberate data snapshot, model endpoint, container image, book, or algorithm version change creates different provenance and may create different results.

## Canonical Run Specification

Before orchestration, the runtime compiles each supported quantitative request into an immutable `RunSpec`. A deterministic domain parser handles:

- Absolute dates and supported date aliases.
- Trading-day and trading-year lookbacks and horizons.
- Scenario, simulation, and path counts.
- Baseline and Chronos reconstruction seeds.
- Supported portfolio identifiers.
- Percentage and decimal stress weights.
- Supported rate shocks in basis points or percent points.
- Supported rate tenors and conditioning periods.
- Named, versioned run profiles such as the stage-safe headline profile.

The compiler canonicalizes equivalent expressions before hashing. For example, five trading years and 1,260 trading days resolve to the same value, while one trading year and 252 trading days resolve to the same horizon.

Each `RunSpec` contains:

- Canonical quantitative parameters.
- Explicit seeds for every stochastic reconstruction step.
- Market-panel snapshot ID and content hash.
- Covariate snapshot ID and content hash.
- Portfolio/book version.
- Chronos endpoint and model version.
- Baseline and Chronos container image digests.
- Blending and pricing algorithm versions.
- A deterministic `spec_hash` derived from canonical inputs and provenance.
- A distinct `execution_id` for each independent execution.

Equivalent prompts produce the same `spec_hash`. Separate attempts produce different `execution_id` values so independent computation can be demonstrated rather than hidden by caching.

The runtime persists the immutable manifest at `runs/<execution_id>/run_spec.json` in the data bucket before it invokes the model. Quantitative tools receive `execution_id`, load that manifest from the deterministic key, and reject a missing or mismatched manifest. The AgentCore runtime role receives narrowly scoped access to create these manifests; tool roles retain access through the existing data-bucket grants.

## Tool Contract And Data Flow

The existing nine-tool architecture remains. Quantitative tools consume the immutable run through `execution_id`; model-generated scalar arguments are not an independent source of truth. Each tool validates that supplied artifacts and any repeated arguments match the stored `RunSpec`.

The canonical flow is:

1. Compile and persist `RunSpec`; stream the resolved specification to the client.
2. `load_data` slices the canonical number of panel observations ending at the canonical as-of date. It also produces an aligned historical covariate artifact.
3. `run_baseline_mc` receives the canonical panel, horizon, path count, component count, and seed.
4. `run_chronos2` receives the same canonical panel length and horizon, plus the aligned VIX, MOVE, and WTI covariates and an explicit reconstruction seed.
5. `blend_paths` classifies tails using the same full cross-asset book used by final pricing.
6. `price_book` prices the parametric, Chronos-only, and blended PathSets.
7. `plot` validates source metadata and renders the baseline-versus-augmented overlay in canonical order.
8. Diagnostics compute contribution attribution and held-out coverage when realized data is available.

`blend_paths`, the point at which both source PathSets and the immutable run are available, writes `runs/<execution_id>/diagnostics.json` and returns its URI with the blended PathSet URI. Attribution, coverage, and `price_book` use shared core pricing and diagnostics functions, so the live tools do not maintain a second calculation implementation.

The live agent workflow and `scripts/calibrate_headline.py` call the same core run-spec, slicing, covariate-alignment, book-loading, blending, pricing, and diagnostics functions. Neither path duplicates defaults.

The stage-safe headline profile currently resolves to:

```text
as_of=2022-09-30
lookback=1260 observations
horizon=252 observations
n_paths=500 per engine
baseline_components=5
baseline_seed=0
chronos_seed=0
w_stress=0.5305
regime_threshold=0.7
book=cross_asset_demo
```

These values are profile data, not special branches spread through the agent, tools, calibration script, or frontend.

## Artifact Identity And Result Labeling

PathSet identity is authoritative. `price_book` derives `scenario_role` from `PathSet.source`:

| PathSet source | Scenario role |
|---|---|
| `parametric` | `baseline` |
| `chronos2` | `chronos_only` |
| `chronos2_conditional` | `chronos_only` |
| `blended` | `augmented` |

Each result includes `execution_id`, `spec_hash`, `scenario_role`, `paths_uri`, `paths_sha256`, metrics, and `metrics_uri`. Labels never depend on invocation or completion order.

The frontend keys exposure rows by `execution_id + scenario_role`. The plot tool reads scenario metadata from the metrics artifacts, places baseline and augmented inputs in canonical order, and rejects duplicate or incompatible roles.

Model prose may interpret the run but is not an authoritative numerical channel. Structured SSE events populate the exposure summary, diagnostics, and plot artifacts directly.

## Structured Streaming

The SSE protocol adds these quantitative events alongside existing text and tool lifecycle events:

- `run_spec`: canonical inputs, provenance, `spec_hash`, and `execution_id`.
- `exposure_result`: source-derived scenario identity and terminal EE, PFE 97.5%, and ES 97.5%.
- `diagnostics`: Chronos contribution and held-out coverage metrics.

Tool attempts retain unique attempt IDs. Failed attempts remain visible but cannot populate summaries or plots. A retry cannot overwrite a successful result under a different identity.

## Chronos Contribution Attribution

Every completed quantitative run reports five distributions:

1. Uniform parametric baseline.
2. Uniform Chronos-only.
3. Reweighted parametric component.
4. Reweighted Chronos component.
5. Final blended distribution.

The report includes terminal EE, PFE 97.5%, and ES 97.5% for each distribution, plus absolute and percentage deltas from the uniform parametric baseline. This distinguishes risk changes caused by Chronos scenarios from changes caused by reweighting parametric tails.

The report describes measured attribution without requiring Chronos-only or blended PFE to be higher. A lower value is valid when supported by coverage and distribution diagnostics; it must not be relabeled or explained as an uplift.

## Held-Out Coverage

Coverage uses only observations after the requested as-of date. Model input panels and covariates end at the as-of date, preventing look-ahead leakage.

### Portfolio Exposure Coverage

For each realized date in the requested horizon:

1. Revalue the canonical book on the realized market-factor path.
2. Convert realized MtM to positive exposure.
3. Compare realized exposure with each model's one-sided PFE 97.5% value for that date.

Report coverage percentage, breach count, average breach magnitude, and maximum breach magnitude for baseline, Chronos-only, and augmented distributions. The nominal target is 97.5%; closeness to nominal is the primary comparison.

### Market-Factor Coverage

For each of the 21 modeled series, compare realized values with each distribution's central 95% path band. Report:

- Overall observation-level coverage.
- Per-series coverage.
- Calm-regime coverage.
- Stress-regime coverage using the canonical threshold.
- Distance from the nominal 95% target.

Coverage is unavailable, rather than estimated, when the curated snapshot does not contain the complete realized horizon.

The diagnostics artifact is structured JSON and carries the same `execution_id`, `spec_hash`, data hashes, model version, image digests, and algorithm versions as the run.

## Error Handling

The workflow fails closed when:

- Prompt compilation leaves a required quantitative field ambiguous.
- A tool argument disagrees with the immutable `RunSpec`.
- A panel, covariate, PathSet, metrics, or diagnostics artifact has the wrong hash or execution identity.
- Covariates required by the canonical run are missing or misaligned.
- The deployed model or container version differs from the pinned provenance.
- Plot inputs do not contain exactly one baseline and one augmented result from the same execution.

Insufficient post-as-of observations mark held-out coverage unavailable without invalidating scenario generation or pricing. The entire request fails only when the user explicitly requires complete held-out coverage as a condition of the run.

Errors are returned verbatim through structured lifecycle events. The model cannot silently substitute defaults or reuse artifacts from another execution.

## Verification Strategy

Development follows test-first red-green cycles. Required automated coverage includes:

- Prompt normalization tests for equivalent wording, units, aliases, and ambiguity rejection.
- RunSpec canonicalization and stable hashing tests.
- Tests proving live and calibration consume the same builder and defaults.
- Data and covariate alignment tests with strict as-of boundaries.
- Tool contract tests for execution and artifact provenance.
- Price-book identity tests with reversed completion order.
- Plot source-order and incompatibility tests.
- Attribution tests that distinguish uniform, component-reweighted, and blended metrics.
- Portfolio and market-factor held-out coverage tests.
- SSE parsing and frontend rendering tests for all structured events.
- Existing core, agent/tool, frontend, relay, and relevant CDK tests.

## Live Acceptance

After rebuilding and deploying affected Lambda, Fargate, AgentCore, and frontend artifacts with Finch, run the exact acceptance prompt three times as independent executions.

All three must satisfy:

- Distinct `execution_id` values.
- Identical `spec_hash` values.
- Identical resolved quantitative inputs and pinned provenance.
- Identical cent-level baseline, Chronos-only, and augmented EE/PFE/ES.
- Correct source-derived labels regardless of tool completion order.
- Independently generated artifacts with valid hashes.
- No failed tool lifecycle events.
- A populated structured exposure summary, attribution report, coverage report, regime plot, and PFE overlay.

Additional wording variants expressing the same request must resolve to the same `spec_hash` and raw results. Ambiguous variants must ask for clarification and must not launch tools.

## Deployment Scope

The expected deployment surface is:

- Lambda tool code and shared layers for RunSpec validation, data/covariate output, blending, pricing, plotting, and diagnostics.
- Baseline and Chronos Fargate images for manifest-driven execution and explicit version provenance.
- AgentCore runtime image for deterministic prompt compilation and structured SSE events.
- AgentCore Gateway schemas when tool contracts change.
- Frontend bundle for provenance-based labeling and diagnostics rendering.

Deployment follows the repository runbook, preserves the CloudFront/OAC/WAF streaming architecture, and uses Finch for Docker-compatible image builds.
