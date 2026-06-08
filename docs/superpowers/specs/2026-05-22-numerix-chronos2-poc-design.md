# Numerix x Chronos-2 PoC — Design

**Status:** Approved — implemented (Plan A + Plan B code-complete on `main`, 2026-06-04; live-data sources rewired for deploy 2026-06-05; streaming edge consolidated into this spec 2026-06-08)
**Date:** 2026-05-22 (Chronos-2 deployment/serving sections refreshed 2026-06-04; live-data + agent-model banner 2026-06-05; streaming-edge consolidation 2026-06-08)
**Author:** Brainstorming session output

> **2026-06-08 streaming-edge consolidation note.** The SPA streams each agent turn over **Server-Sent Events** so the room watches the copilot reason and call tools live — a Plan B architecture invariant from the start (the streaming Function URL with `InvokeMode=RESPONSE_STREAM`). The original §5 body predated the post-implementation re-sync and never drew it, so this revision folds the streaming edge into §3, §5, and §9 as native architecture: an **SSE relay Lambda** (Function URL, `RESPONSE_STREAM`, `AWS_IAM`) fronted by **CloudFront + WAF** with an Origin Access Control (SigV4) as the sole invoker, alongside the API-Gateway control plane that serves sessions and the synchronous `/invoke` fallback. This supersedes the standalone `2026-06-07-sse-cloudfront-waf-design.md` spec, whose content now lives here. The augmentation thesis, narrative arc, and pricing path are unchanged.

> **2026-06-04 re-architecture note.** The original design assumed Chronos-2 ran on a hand-rolled **SageMaker real-time endpoint returning sample paths**. The implemented system instead deploys Chronos-2 via **AutoGluon Cloud (serverless default)**, which returns **per-series quantiles**; the client reconstructs joint `(n_paths, horizon, n_series)` paths client-side via inverse-CDF marginals coupled by a lookback Gaussian copula. The two `run_*` tools became **async ECS Fargate tasks** with paired `check_*` poll tools (so the live tool surface is **9 tools**, not 7). §5–§9 below have been updated to reflect this; the augmentation story, narrative, and evaluation are unchanged.

> **2026-06-04 scope-extension note.** This spec is normally frozen post-implementation (see `CLAUDE.md`), but a partner-objectives review prompted three sanctioned additions, captured here and planned in **Plan A part-4** (Stages 10–12) and **Plan B part-10** (Stage 10). The additions sharpen the cross-asset and acceleration stories the partner cares about most:
> 1. **Cross-asset factor universe (rates + FX + equity + credit).** Add equity indices **SPX, NIKKEI225** and credit spreads **US_IG_OAS, US_HY_OAS** as series modeled jointly by *both* engines, plus two new priced instruments (equity forward, CDS-protection proxy) so equity and credit actually move EE/PFE/ES. Panel grows from ~17 to ~21 series. (§4, §6.)
> 2. **Genuine headline + live what-if.** A live **calibration script** queries the *real* Chronos-2 endpoint once and records the measured PFE delta to a committed artifact (the hermetic test suite stays offline). The **what-if conditioning** path — already supported in the Plan A core — is wired end-to-end through the Fargate entrypoint, the `run_chronos2` tool schema, the system prompt, and the frontend form. (§6, §8, §10.)
> 3. **Nested-MC-vs-FM latency benchmark.** A small but real **nested Monte Carlo** exposure engine (outer scenarios × inner revaluation) is added as a *benchmark reference* — never the demo's pricing path — and timed head-to-head against the FM-path + closed-form pipeline, with the speedup recorded to a committed artifact. (§8.)
>
> The augmentation thesis, the "augment-not-replace" framing, and the §3 narrative are unchanged. Vol-surface forecasting remains a closing-tour beat only (§10), not a live capability.

> **2026-06-05 live-data + deploy note.** Standing the PoC up for a live demo surfaced that the shipped §3 data fetchers targeted endpoints that have since changed, and the agent pinned an end-of-life model. Captured here and planned in **Plan A part-5** (Stage 13) + the deploy runbook; the augmentation thesis, narrative, and pricing path are unchanged.
> 1. **All-live market data sources.** FRED now uses the **keyed JSON API** (the unkeyed CSV endpoint is rate-limited); ECB FX moved to **`data-api.ecb.europa.eu`** and is EUR-base-only, so USD crosses are **triangulated** (`USD{CCY}=D.USD.EUR/D.{CCY}.EUR`); **SPX/NIKKEI225 + MOVE** come from the **Yahoo Finance chart API** (FRED lacks MOVE entirely and caps equities); and credit OAS uses a deep free **`BAA10Y` proxy** (Moody's Baa−10Y Treasury, to 1986) because **ICE BofA OAS is licence-locked to a rolling ~3-year window on FRED** (no deep history, no ALFRED archive). `US_IG_OAS=BAA10Y`, `US_HY_OAS=1.7×BAA10Y`; columns keep their names + percent units but are a **proxy**, not the original ICE series. `snapshot_data.py` now also emits `regimes.parquet`, and a new `seed_demo_data.py` uploads the curated panel to the S3 data bucket the Lambda tools read.
> 2. **Agent reasoning model.** The AgentCore runtime model moves from the end-of-life `anthropic.claude-3-5-sonnet-20241022-v2:0` to **`us.anthropic.claude-sonnet-4-6`** (a cross-region inference profile; the runtime IAM policy grants the profile ARN + underlying foundation-model ARNs). Model choice remains configurable via `MODEL_ID`.

## 1. Purpose & Audience

A demoable proof-of-concept for **Numerix**, a financial services partner whose hybrid model-based Monte Carlo framework generates the scenarios that feed exposure, PFE, and XVA calculations. The demo shows how **Amazon Chronos-2**, a time-series foundation model, can be used as an *augmentation* layer — not a replacement — for that framework.

**Primary audience:** Numerix quants and product owners who know PFE/XVA cold. They need to see (a) Chronos-2 plugging into a pipeline that resembles theirs, (b) measurable changes to tail risk numbers under stress, and (c) what an analyst's interactive workflow looks like.

**Single takeaway:** Chronos-2 is not a Monte Carlo replacement. It augments the **input path set** to the existing exposure machinery, closing the gap between parametric assumptions and observed joint-tail behavior. The pricing/exposure code path is unchanged; only the scenarios it consumes change.

## 2. Augmentation Framing

> Chronos-2 augments the Numerix hybrid Monte Carlo framework by forecasting the joint evolution of dense market factors and covariates, then using those forecasts to **condition, correct, reweight, or enrich** the scenarios that feed exposure, PFE, and XVA calculations — while leaving the arbitrage-aware pricing and exposure machinery in Numerix intact.

The demo's **headline** is **correct + reweight** (regime-aware tail correction). **Condition** appears as the analyst-driven what-if interaction. **Enrich** appears via exogenous covariates fed only to Chronos-2 (see §6).

## 3. Demo Narrative

A ~10-minute live story arc in six beats:

1. **Setup (1 min)** — Analyst opens the copilot and asks: *"Compute baseline PFE on the demo XCCY book over the next year, using the parametric MC."* The reply streams back token-by-token (SSE) so the room watches the copilot reason and call each tool in turn. Result: standard PFE curve.
2. **Reveal (2 min)** — *"Now run the same calculation against the 2022 rate-hike window, comparing baseline vs. Chronos-2 augmented scenarios."* Two PFE curves overlaid; a regime indicator highlights where the augmented one diverges. Headline metric: *97.5% PFE understated by X% / $Y million on this book.* (X and Y are measured during build and pinned for the demo — see §8.)
3. **Explain (3 min)** — *"Why are they different? Show me sample paths."* Sample joint paths from both engines (parametric thin-tailed vs. Chronos-2 capturing FX-rates correlation breakdown). Toggle covariates off; show how the divergence narrows. Confirm the same pricing/exposure code ran for both — only the path set changed.
4. **Interact (2 min)** — *"What if EUR rates +100bp and USD/JPY −10% over 30 days?"* Conditional Chronos-2 generation; PFE recomputed live.
5. **Where else (1 min)** — *"Where else could this apply in our pipeline?"* Curated tour of adjacent use cases (covered in §10).
6. **Wrap (~30s)** — Same engine, augmented inputs, materially different tail risk number, broader capability frontier visible.

## 4. Scope: Asset Class, Portfolio, Stress Windows

**Risk-factor universe (~21 series) — modeled jointly by *both* engines:**
- **FX (daily spot):** USD/EUR, USD/JPY, USD/GBP, USD/CHF, USD/CAD.
- **Rates (daily swap rates / equivalents):** 2y, 5y, 10y for USD, EUR, JPY, GBP.
- **Equity (daily index level):** SPX (S&P 500), NIKKEI225. *(Added 2026-06-04 — see scope-extension note.)*
- **Credit (daily option-adjusted spread):** US_IG_OAS, US_HY_OAS (ICE BofA US Investment-Grade and High-Yield OAS). *(Added 2026-06-04.)*

The equity and credit series are **priced factors**, not covariates: the parametric PCA engine and the Chronos-2 copula both consume them, and the demo book holds instruments sensitive to them (below). This makes the cross-asset story — joint rates + FX + equity + credit dynamics — concrete rather than gestured at.

**Exogenous covariates (Chronos-2 only — see §6):**
- VIX (equity implied vol), MOVE (rates implied vol), front-month WTI (energy / inflation proxy).

**History:** ~15 years of daily observations (2010–2025), explicitly covering stress windows: 2011 EUR sovereign crisis, 2015 SNB CHF unpeg, 2020 COVID, 2022 rate hike cycle.

**Sample portfolio: cross-asset book anchored on a cross-currency swap book.** 8–10 cross-currency basis swaps (mix of EUR/USD, JPY/USD, GBP/USD; tenors 2y/5y/10y; varying notionals and directions) — Numerix-native, sensitive simultaneously to FX and rates. Augmented (2026-06-04) with **two cross-asset instruments** so equity and credit move the exposure metrics: an **equity forward / total-return leg** (on SPX or NIKKEI225, FX-converted to USD) and a **single-name/index CDS-protection proxy** (MtM driven by the OAS series via a duration RPV01). These are closed-form level-driven proxies in the same style as the XCCY valuation — exactly where joint-tail correction across asset classes matters.

**Data sources:** FRED for rates, equity indices (SP500, NIKKEI225), and credit OAS (BAMLC0A0CM, BAMLH0A0HYM2); ECB/BoE/BoJ for FX; public sources for covariates. A pre-loaded snapshot lives in S3 so the demo is reproducible and offline-capable; live API fetches are a supporting capability only.

## 5. System Architecture

```
                          ┌─────────────────────┐
                          │  Analyst (browser)  │
                          │  Chat UI + Charts   │
                          └──────────┬──────────┘
                                     │  HTTPS
                                     ▼
                          ┌─────────────────────┐
                          │  Amplify Hosting    │
                          │  Cloudscape SPA     │
                          └─────┬─────────┬─────┘
            sessions / sync     │         │   streamed turn (SSE)
                                ▼         ▼
                ┌─────────────────┐    ┌─────────────────────┐
                │  API Gateway    │    │  CloudFront + WAF    │
                │ + Lambda authz  │    │  (OAC, SigV4)        │
                └────────┬────────┘    └──────────┬──────────┘
                         │                        ▼
                         │             ┌─────────────────────┐
                         │             │ SSE Relay Lambda     │
                         │             │ (Function URL,       │
                         │             │ RESPONSE_STREAM,     │
                         │             │ AWS_IAM)             │
                         │             └──────────┬──────────┘
                         ▼                        ▼
                          ┌─────────────────────────────┐
                          │  Bedrock AgentCore          │
                          │  Quant Copilot              │
                          │  (Claude reasoning)         │
                          └──────┬─────┬────────────────┘
                                 │     │   tool calls
              ┌──────────────────┘     └─────────────────┐
              ▼                                          ▼
   ┌─────────────────────┐                    ┌─────────────────────┐
   │ Data Tool (Lambda)  │                    │ Curated Knowledge   │
   │ S3 → aligned panel  │                    │ (use-case tour      │
   │  + covariates       │                    │  content)           │
   └──────────┬──────────┘                    └─────────────────────┘
              │
              ▼
   ┌─────────────────────┐    ┌──────────────────────────────────┐
   │ Baseline MC Tool    │    │ Chronos-2 Inference Tool         │
   │ ECS Fargate task    │◄──►│ ECS Fargate task → AutoGluon     │
   │ Hull-White + GBM    │    │ Cloud serverless endpoint        │
   │ + PCA correlation   │    │ (per-series quantiles → joint    │
   │ (no covariates)     │    │  paths via lookback copula;      │
   │                     │    │  covariates; optional cond.)     │
   └──────────┬──────────┘    └──────────────┬───────────────────┘
              │                              │
              └──────────┬───────────────────┘
                         ▼
              ┌─────────────────────────────┐
              │ Reweighting / Regime Tool   │
              │ (Lambda)                    │
              │ Regime detector +           │
              │ tail-augmentation logic     │
              └──────────┬──────────────────┘
                         ▼
              ┌─────────────────────────────┐
              │ Pricing & Exposure Tool     │
              │ (Lambda)                    │
              │ XCCY book → EE / PFE / ES   │
              └──────────┬──────────────────┘
                         ▼
              ┌─────────────────────────────┐
              │ Plotting Tool (Lambda)      │
              │ Fan charts, PFE overlays,   │
              │ regime ribbons              │
              └─────────────────────────────┘
```

**Component responsibilities — each is a tool the copilot can invoke:**

- **Data Tool** — fetches and aligns the FX/rates panel and covariate block from S3, attaches regime labels.
- **Baseline MC Tool** — parametric joint scenario engine: PCA on factor returns + Hull-White short-rate dynamics + GBM-style FX, Cholesky-driven joint sampling. Does **not** consume covariates.
- **Chronos-2 Inference Tool** — an async ECS Fargate task that calls a Chronos-2 endpoint deployed via AutoGluon Cloud (serverless default). The endpoint returns per-series probabilistic **quantiles**; the client reconstructs joint paths via a lookback Gaussian copula. Supports unconditional joint forecast, conditioning by prefix observations, and exogenous covariates. (Launched by a thin `run_chronos2` Lambda; polled via `check_chronos2`.)
- **Reweighting / Regime Tool** — the augmentation layer. Detects regime, scores parametric vs. Chronos-2 path sets against historical conditional behavior, produces a blended weighted path tensor.
- **Pricing & Exposure Tool** — the "Numerix machinery" stand-in: XCCY book valuation along each path → EE/PFE/ES. Identical interface for parametric, augmented, or Chronos-2-only inputs.
- **Plotting Tool** — emits chart artifacts (PNG to S3) the front-end renders.
- **Curated Knowledge** — pre-authored adjacent-use-case briefs the agent draws from for the closing tour beat.

**Two front-door paths — sync control plane + streamed agent turn.** The SPA talks to two surfaces:
- **API Gateway (+ Lambda authorizer)** — the request/response control plane: session create/list/append (`/sessions`) and a synchronous, non-streaming `/invoke` fallback. Demo-grade `x-api-key`; Cognito-swappable.
- **SSE Relay (Lambda Function URL, `InvokeMode=RESPONSE_STREAM`)** fronted by **CloudFront + WAF** — the streamed agent turn. The relay invokes AgentCore and relays the response token-by-token as Server-Sent Events so the analyst watches the copilot reason and call tools live. Streaming requires a Function URL (API Gateway REST buffers responses and breaks SSE) and a browser `fetch` + `ReadableStream` reader (not `EventSource`, which cannot send the `x-api-key` header). The Function URL is `AWS_IAM`; a CloudFront **Origin Access Control** (SigV4, signing always) is the only principal that can invoke it, so it is never publicly reachable. The fronting CloudFront distribution carries a **WAF WebACL** (AWS Managed Common + Known-Bad-Inputs rule groups + a per-IP rate rule), disables caching so the stream is not buffered, and forwards `x-api-key` to the relay, which re-checks it at the application layer as defense in depth.

**Three design notes worth flagging:**
- The pricing/exposure tool is **a faithful stand-in, not real Numerix code.** This is an explicit boundary so the partner conversation is honest.
- The **Reweighting/Regime Tool is its own component**, not buried inside the Chronos-2 tool. The augmentation logic is the most-scrutinized piece; isolating it makes it inspectable.
- **Streaming is the primary demo path; `/invoke` is the fallback.** The full headline chain (`load_data → run_baseline_mc → run_chronos2 → blend_paths → price_book → plot`) runs multiple minutes — well past API Gateway's 29 s integration cap — so the live walkthrough uses the SSE path; the synchronous `/invoke` exists for scripted/non-streaming use and short turns.

## 6. Augmentation Mechanics

The piece quants will scrutinize first.

**Step 1 — Generate two parallel path sets.** Both keyed off the same as-of date and same lookback context, over the **full ~21-series cross-asset universe** (rates + FX + equity + credit — see §4).
- **Parametric:** N=5,000 joint paths over horizon H (e.g., 1y daily). PCA + Hull-White + GBM-style FX, Cholesky-driven joint sampling. The PCA factor basis spans all asset classes, so equity/credit co-movement enters through the shared factor loadings.
- **Chronos-2:** N=5,000 joint paths via the AutoGluon Cloud endpoint. The endpoint returns per-series probabilistic quantiles over the same horizon (conditioned on the same context **plus exogenous covariates** — VIX, MOVE, WTI); the client reconstructs the joint `(n_paths, horizon, n_series)` set by inverse-CDF marginal sampling coupled with a lookback Gaussian copula (cross-series correlation estimated from the shared lookback window). The copula is dimension-agnostic, so adding equity and credit series is a data change, not an engine change.

**Step 2 — Detect regime context.** Look at the trailing 20–60 days of realized factor behavior up to the as-of date. Compute a small, transparent feature set (rolling vol, FX-rates correlation level, vol-of-vol). Map to a regime weight `w_stress ∈ [0, 1]`:
- `0` = calm regime → trust parametric
- `1` = stress regime → lean toward Chronos-2 in the tail
- Anything between blends.

The regime detector is a **deterministic rule set**, not a learned model. It is shown to the audience as part of the explanation.

**Step 3 — Blend the path sets.** Two stacked operations:
- **Tail-region reweighting:** define the "tail" as paths whose terminal portfolio P&L falls in the top/bottom 5%. In the tail bucket: parametric weight = `(1 - w_stress)`, Chronos-2 weight = `w_stress`. In the body: parametric weight stays high (e.g., 0.9), Chronos-2 contributes a small mixing component (0.1) so the augmentation is visible even in calm regimes.
- **Importance weighting, not deletion:** every path keeps a non-zero weight. The PFE/EE computation downstream sums weighted exposures. Quants will recognize this as standard importance sampling — that is the point.

**Step 4 — PFE/EE on the blended set.** The pricing tool already accepts (paths, weights). Same machinery for parametric-only (uniform weights), Chronos-2-only, and augmented runs. The audience sees three lines on one chart.

**Conditional generation (what-if beat):** when the analyst describes a stress narrative, the agent calls Chronos-2 with the conditioning passed as a per-series `anchor` known-covariate over the first `n_anchor_days` of the horizon (the Plan A `Conditioning` dataclass: `series_shifts` + `n_anchor_days`). Reweighting uses `w_stress = 1` for the conditional view since it is an explicit stress scenario by construction. As of the 2026-06-04 scope extension this path is wired **end-to-end** — frontend what-if form → `run_chronos2` tool schema (`conditioning` arg) → Fargate entrypoint (`CONDITIONING_JSON` → `simulate_chronos2(conditioning=…)`) — so the what-if beat runs live through the copilot/UI, not only in the notebook.

**Calibration / fairness:** both engines share the **same lookback window** for like-for-like comparison. The covariate asymmetry (Chronos-2 only) is acknowledged as part of the value story — capturing exogenous signals classical PCA + parametric stacks cannot.

**What we deliberately do not do:**
- Train or fine-tune Chronos-2 — zero-shot/in-context only.
- Replace the parametric model anywhere — it always runs.
- Hide the weights — the demo can display them on request.

## 7. Agent Behavior & Tool Surface

**Reasoning model:** Claude (via AgentCore — model choice configurable; default Sonnet-class for tool-use latency).

**Tool surface:**

| Tool | Purpose | Returns |
|---|---|---|
| `load_data(as_of_date, lookback_days)` | Aligned panel + covariates + regime labels from S3 | Panel handle (S3 URI) |
| `run_baseline_mc(panel, horizon, n_paths)` | Launch parametric joint scenarios (no covariates) as an async Fargate task | `{task_arn, paths_uri}` |
| `check_baseline_mc(task_arn, paths_uri)` | Poll the baseline-MC Fargate task | `{task_status, ready, paths_uri}` |
| `run_chronos2(panel, horizon, n_paths, covariates?, conditioning?)` | Launch Chronos-2 joint forecast (zero-shot; optional what-if `conditioning`) as an async Fargate task | `{task_arn, paths_uri}` |
| `check_chronos2(task_arn, paths_uri)` | Poll the Chronos-2 Fargate task | `{task_status, ready, paths_uri}` |
| `blend_paths(parametric_paths, chronos_paths, w_stress)` | Reweighting / regime augmentation | Weighted paths handle |
| `price_book(paths)` | XCCY exposure → EE/PFE/ES | Metrics + per-time-bucket tensor |
| `plot(spec)` | Renders fan charts, PFE overlays, regime ribbons | Image S3 URI |
| `lookup_use_case(topic)` | Curated knowledge for the closing tour | Markdown brief |

> The two `run_*` tools are **asynchronous launchers** (they start a Fargate task and return a handle); the agent polls the matching `check_*` tool until `ready` before consuming `paths_uri`. The conditioning/what-if prefix is supported by the core `simulate_chronos2` and — as of the 2026-06-04 scope extension (Plan B part-10) — is wired end-to-end: `run_chronos2` accepts an optional `conditioning` arg (`{series_shifts, n_anchor_days}`), the Fargate entrypoint reads `CONDITIONING_JSON`, and the frontend what-if form emits it.

**Constraints on the agent:**
- Cannot author math or run code outside this tool surface.
- Tool results pass through unmodified — no agent-paraphrased numbers.
- For the closing "where else does this apply" beat, the agent only draws from `lookup_use_case`.

**Acceptance scenarios:**

1. *"Compute baseline PFE on the demo XCCY book over 1y."* → `load_data` → `run_baseline_mc` → `price_book` → `plot` → return chart + headline.
2. *"Now compare against Chronos-2 augmented scenarios in the 2022 stress window."* → `load_data(stress)` → `run_baseline_mc` + `run_chronos2` → `blend_paths` → `price_book(×2)` → `plot` overlay.
3. *"Why are they different? Show me sample paths."* → `plot(sample_paths)` + `plot(weights_by_regime)`.
4. *"What if EUR rates +100bp and USD/JPY −10% over 30 days?"* → `run_chronos2(conditioning=...)` → `price_book` → `plot`.
5. *"Where else could this be applied in our pipeline?"* → `lookup_use_case` → curated shortlist.

**Safety rails:** AgentCore tool-call traces logged to CloudWatch — useful for prod debug *and* to show the audience the call graph if asked.

## 8. Evaluation

Three layers, in increasing technical depth:

- **Headline metric (for the room):** delta in 97.5% PFE between baseline and augmented runs in the chosen stress window, expressed in percent and notional dollars on the demo book. One number on the title slide. **Provenance (2026-06-04):** the *genuine* number is produced by a live **calibration script** (`scripts/calibrate_headline.py`) that queries the real Chronos-2 endpoint once on the real snapshot and records the measured baseline/augmented PFE, `delta_pct`, `delta_usd`, as-of date, window, `n_paths`, endpoint name, git SHA, and timestamp to a committed artifact (`docs/results/headline_calibration.json`). The hermetic regression test (`tests/test_headline_numbers.py`) remains a *plumbing* guard against a frozen synthetic panel through a fake endpoint — it pins direction and order of magnitude, **not** the live number. Re-run the calibration script before each demo so the title-slide figure reflects the current model.
- **Quant-defensible diagnostics (for the technical Q&A):**
  - **Regime-conditional coverage:** in held-out stress windows, what fraction of realized P&L outcomes fall outside the parametric 97.5% PFE band vs. the augmented band? Augmented should track closer to nominal coverage.
  - **Joint-tail dependence:** empirical vs. parametric vs. Chronos-2 tail correlation on held-out data (e.g., exceedance correlation between rates and FX in the bottom 5% region).
  - **Distribution sanity:** KS or energy-distance between path-set marginals and held-out empirical, by regime.
- **Operational metrics (for the platform Q&A):** end-to-end latency (data → blended PFE), Chronos-2 endpoint p50/p95 latency, scenario throughput.
  - **Nested-MC-vs-FM latency benchmark (2026-06-04):** to support the "reduce reliance on nested Monte Carlo" objective, a small but real **nested Monte Carlo** exposure engine (`models/nested_mc.py` — outer factor scenarios × inner revaluation sub-paths at each exposure date) is timed head-to-head against the FM-path-generation + closed-form pricing pipeline on the same book. A non-test script (`scripts/benchmark_latency.py`) records wall-clock per stage, total inner-revaluation count, and the speedup multiple to a committed artifact (`docs/results/latency_benchmark.json`). **Framing:** nested MC is a *benchmark reference only* — the demo still prices closed-form along FM/parametric paths; the strawman exists to quantify the cost the foundation-model approach avoids. A hermetic test asserts the nested engine's *correctness* (in the zero-inner-volatility limit its PFE collapses to the closed-form PFE), never timing.

All three are computed once and **pinned** for the demo so headlines do not drift between dry-runs and live presentations. They are also accessible via a "diagnostics" view the agent can summon if asked.

## 9. AWS Footprint

| Component | Service | Notes |
|---|---|---|
| Front-end | Amplify Hosting | Cloudscape React SPA |
| API (control plane) | API Gateway + Lambda authorizer | Sessions + synchronous `/invoke` fallback; demo-grade API key; Cognito-swappable |
| Streaming edge | CloudFront + WAF → SSE Relay Lambda (Function URL, `RESPONSE_STREAM`) | Token-by-token SSE for the live agent turn. Function URL is `AWS_IAM`; CloudFront OAC (SigV4) is the only invoker; WAF WebACL (AWS Managed Common + Known-Bad-Inputs + per-IP rate rule); caching disabled so the stream is unbuffered; `x-api-key` forwarded and re-checked in the relay |
| Agent | Bedrock AgentCore | Claude (Sonnet-class default); CloudWatch traces |
| Data tool | Lambda | Reads S3 panel + covariates |
| Baseline MC | ECS Fargate task (launcher + poll Lambdas) | Python (numpy/scipy); on-demand; own ECR image |
| Chronos-2 | ECS Fargate task (launcher + poll Lambdas) → AutoGluon Cloud serverless endpoint | Fargate image bundles `autogluon-cloud` (too heavy for a Lambda layer); task role holds `sagemaker:InvokeEndpoint`. Serverless endpoint = CPU, scales to zero between demos (`ml.g5.xlarge` realtime is an optional fallback). |
| Blend / pricing | Lambda | Pure Python; vectorized over paths |
| Plotting | Lambda | matplotlib → S3 PNG; FE renders the URI |
| Storage | S3 | Panel, covariates, regime labels, sample book, plots, traces |
| Observability | CloudWatch Logs + X-Ray | AgentCore tool traces; per-Lambda error alarms + dashboard |
| IAM | Per-tool least-privilege roles | Standard |

**Cost shape:** the serverless Chronos-2 endpoint scales to zero between demos, so steady-state cost is near-zero; the dominant run-time cost is the two on-demand Fargate tasks while a scenario set is generating. Single-region (us-east-1).

## 10. Closing Tour: Adjacent Use Cases

The agent's `lookup_use_case` knowledge is pre-authored and covers two categories of content:

**A. Adjacent FSI use cases for the same Chronos-2 deployment pattern (correct + reweight + condition):**
- Stress test design (regulatory + internal)
- IM / VM forecasting
- FRTB IMA expected shortfall augmentation
- Market-data gap-filling for stale or sparse series
- Scenario-based limits monitoring

**B. Capabilities not exercised in the live demo, with named adjacent use cases:**
- **Long context windows** — regime conditioning across multi-cycle history; structural shifts (rates regime changes, FX peg breaks); decade-spanning backtests without rolling recalibration.
- **Temporal hierarchies (intraday ↔ daily ↔ macro)** — intraday liquidity-aware exposure; vol-surface forecasting at multiple frequencies; intraday VaR augmentation; event-window risk (FOMC, NFP).

The agent serves these deterministically — no freelancing.

## 11. Out of Scope (V1)

Lines we will not cross in this PoC:
- Real Numerix Analytics integration (pricing/exposure tool is a faithful stand-in).
- Fine-tuning Chronos-2 (zero-shot only).
- Live market-data pipelines (pre-loaded snapshot in S3).
- Authentication beyond a demo-grade API key.
- More than one portfolio in the live demo (the single cross-asset book — XCCY swaps + one equity forward + one CDS proxy — is the only book; the factor universe is rates + FX + equity + credit as of 2026-06-04, but no further asset classes, e.g. commodities-as-factors or inflation).
- Production-grade model risk documentation (we gesture at it; we do not write the validation report).
- Full SR 11-7-style backtest harness; we have just enough diagnostics to defend the headline.
- A production nested-MC exposure engine. The 2026-06-04 `models/nested_mc.py` is a deliberately small benchmark strawman (toy outer/inner sizes) for the latency comparison only — not a curve-consistent, calibrated inner-revaluation engine, and never the demo's pricing path.
- Vol-surface forecasting (smile/skew dynamics, recalibration-cycle reduction) — remains a closing-tour talking point (§10), not a live or benchmarked capability. No options/strikes data is in scope.
- Mobile, offline, multi-tenant.
- Regulatory artifacts (FRTB capital, BCBS-mandated stress tables).
- Intraday data and long (multi-decade) context windows in the live demo — these appear only in the closing tour.

## 12. Risks & Open Questions

- **Chronos-2 quality on the joint rates + FX + equity + credit universe is the single biggest unknown.** Mitigation: the `scripts/calibrate_headline.py` calibration run (§8) measures the real-endpoint PFE delta on a held-out stress window *before* committing the demo narrative; the recorded artifact is the go/no-go signal. If it does not beat parametric materially in stress, reframe the story (still useful, but show what it does demonstrate honestly). Adding equity and credit widens this unknown — the cross-asset joint behavior is exactly what the calibration run must validate, not assume.
- **Same-lookback calibration may favor one engine for some regimes.** Mitigation: pre-pick the as-of dates so the comparison is honest; document selection criteria.
- **Reweighting could be argued as cherry-picking.** Mitigation: weights are deterministic functions of the regime detector; show the function.
- **Covariate asymmetry (Chronos-2 sees VIX/MOVE/WTI; parametric does not)** is an honest disadvantage for the parametric baseline. Mitigation: explicitly call this out as part of the value story — "this is something Chronos-2 can do that classical PCA + parametric cannot, without rebuild."
