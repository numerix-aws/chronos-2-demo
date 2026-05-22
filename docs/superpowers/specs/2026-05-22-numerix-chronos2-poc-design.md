# Numerix x Chronos-2 PoC — Design

**Status:** Approved (pending user spec review)
**Date:** 2026-05-22
**Author:** Brainstorming session output

## 1. Purpose & Audience

A demoable proof-of-concept for **Numerix**, a financial services partner whose hybrid model-based Monte Carlo framework generates the scenarios that feed exposure, PFE, and XVA calculations. The demo shows how **Amazon Chronos-2**, a time-series foundation model, can be used as an *augmentation* layer — not a replacement — for that framework.

**Primary audience:** Numerix quants and product owners who know PFE/XVA cold. They need to see (a) Chronos-2 plugging into a pipeline that resembles theirs, (b) measurable changes to tail risk numbers under stress, and (c) what an analyst's interactive workflow looks like.

**Single takeaway:** Chronos-2 is not a Monte Carlo replacement. It augments the **input path set** to the existing exposure machinery, closing the gap between parametric assumptions and observed joint-tail behavior. The pricing/exposure code path is unchanged; only the scenarios it consumes change.

## 2. Augmentation Framing

> Chronos-2 augments the Numerix hybrid Monte Carlo framework by forecasting the joint evolution of dense market factors and covariates, then using those forecasts to **condition, correct, reweight, or enrich** the scenarios that feed exposure, PFE, and XVA calculations — while leaving the arbitrage-aware pricing and exposure machinery in Numerix intact.

The demo's **headline** is **correct + reweight** (regime-aware tail correction). **Condition** appears as the analyst-driven what-if interaction. **Enrich** appears via exogenous covariates fed only to Chronos-2 (see §6).

## 3. Demo Narrative

A ~10-minute live story arc in six beats:

1. **Setup (1 min)** — Analyst opens the copilot and asks: *"Compute baseline PFE on the demo XCCY book over the next year, using the parametric MC."* Result: standard PFE curve.
2. **Reveal (2 min)** — *"Now run the same calculation against the 2022 rate-hike window, comparing baseline vs. Chronos-2 augmented scenarios."* Two PFE curves overlaid; a regime indicator highlights where the augmented one diverges. Headline metric: *97.5% PFE understated by X% / $Y million on this book.* (X and Y are measured during build and pinned for the demo — see §8.)
3. **Explain (3 min)** — *"Why are they different? Show me sample paths."* Sample joint paths from both engines (parametric thin-tailed vs. Chronos-2 capturing FX-rates correlation breakdown). Toggle covariates off; show how the divergence narrows. Confirm the same pricing/exposure code ran for both — only the path set changed.
4. **Interact (2 min)** — *"What if EUR rates +100bp and USD/JPY −10% over 30 days?"* Conditional Chronos-2 generation; PFE recomputed live.
5. **Where else (1 min)** — *"Where else could this apply in our pipeline?"* Curated tour of adjacent use cases (covered in §10).
6. **Wrap (~30s)** — Same engine, augmented inputs, materially different tail risk number, broader capability frontier visible.

## 4. Scope: Asset Class, Portfolio, Stress Windows

**Risk-factor universe (~17–18 series):**
- **FX (daily spot):** USD/EUR, USD/JPY, USD/GBP, USD/CHF, USD/CAD.
- **Rates (daily swap rates / equivalents):** 2y, 5y, 10y for USD, EUR, JPY, GBP.

**Exogenous covariates (Chronos-2 only — see §6):**
- VIX (equity implied vol), MOVE (rates implied vol), front-month WTI (energy / inflation proxy).

**History:** ~15 years of daily observations (2010–2025), explicitly covering stress windows: 2011 EUR sovereign crisis, 2015 SNB CHF unpeg, 2020 COVID, 2022 rate hike cycle.

**Sample portfolio: cross-currency swap book.** 8–10 cross-currency basis swaps (mix of EUR/USD, JPY/USD, GBP/USD; tenors 2y/5y/10y; varying notionals and directions). Numerix-native instrument, sensitive simultaneously to FX and rates — exactly where joint-tail correction matters.

**Data sources:** FRED for rates, ECB/BoE/BoJ for FX, public sources for covariates. A pre-loaded snapshot lives in S3 so the demo is reproducible and offline-capable; live API fetches are a supporting capability only.

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
                          └──────────┬──────────┘
                                     │
                                     ▼
                          ┌─────────────────────┐
                          │  API Gateway        │
                          │  + Lambda authorizer│
                          └──────────┬──────────┘
                                     ▼
                          ┌─────────────────────┐
                          │  Bedrock AgentCore  │
                          │  Quant Copilot      │
                          │  (Claude reasoning) │
                          └──────┬─────┬────────┘
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
   │ ECS Fargate task    │◄──►│ SageMaker real-time endpoint     │
   │ Hull-White + GBM    │    │ (joint multi-series forecast,    │
   │ + PCA correlation   │    │  optional exogenous covariates,  │
   │ (no covariates)     │    │  optional conditioning prefix)   │
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
- **Chronos-2 Inference Tool** — wraps a SageMaker real-time endpoint. Supports unconditional joint forecast, conditioning by prefix observations, and exogenous covariates.
- **Reweighting / Regime Tool** — the augmentation layer. Detects regime, scores parametric vs. Chronos-2 path sets against historical conditional behavior, produces a blended weighted path tensor.
- **Pricing & Exposure Tool** — the "Numerix machinery" stand-in: XCCY book valuation along each path → EE/PFE/ES. Identical interface for parametric, augmented, or Chronos-2-only inputs.
- **Plotting Tool** — emits chart artifacts (PNG to S3) the front-end renders.
- **Curated Knowledge** — pre-authored adjacent-use-case briefs the agent draws from for the closing tour beat.

**Two design notes worth flagging:**
- The pricing/exposure tool is **a faithful stand-in, not real Numerix code.** This is an explicit boundary so the partner conversation is honest.
- The **Reweighting/Regime Tool is its own component**, not buried inside the Chronos-2 tool. The augmentation logic is the most-scrutinized piece; isolating it makes it inspectable.

## 6. Augmentation Mechanics

The piece quants will scrutinize first.

**Step 1 — Generate two parallel path sets.** Both keyed off the same as-of date and same lookback context.
- **Parametric:** N=5,000 joint paths over horizon H (e.g., 1y daily). PCA + Hull-White + GBM-style FX, Cholesky-driven joint sampling.
- **Chronos-2:** N=5,000 joint paths via SageMaker. Multi-series probabilistic forecast over the same horizon, conditioned on the same context **plus exogenous covariates** (VIX, MOVE, WTI).

**Step 2 — Detect regime context.** Look at the trailing 20–60 days of realized factor behavior up to the as-of date. Compute a small, transparent feature set (rolling vol, FX-rates correlation level, vol-of-vol). Map to a regime weight `w_stress ∈ [0, 1]`:
- `0` = calm regime → trust parametric
- `1` = stress regime → lean toward Chronos-2 in the tail
- Anything between blends.

The regime detector is a **deterministic rule set**, not a learned model. It is shown to the audience as part of the explanation.

**Step 3 — Blend the path sets.** Two stacked operations:
- **Tail-region reweighting:** define the "tail" as paths whose terminal portfolio P&L falls in the top/bottom 5%. In the tail bucket: parametric weight = `(1 - w_stress)`, Chronos-2 weight = `w_stress`. In the body: parametric weight stays high (e.g., 0.9), Chronos-2 contributes a small mixing component (0.1) so the augmentation is visible even in calm regimes.
- **Importance weighting, not deletion:** every path keeps a non-zero weight. The PFE/EE computation downstream sums weighted exposures. Quants will recognize this as standard importance sampling — that is the point.

**Step 4 — PFE/EE on the blended set.** The pricing tool already accepts (paths, weights). Same machinery for parametric-only (uniform weights), Chronos-2-only, and augmented runs. The audience sees three lines on one chart.

**Conditional generation (what-if beat):** when the analyst describes a stress narrative, the agent calls Chronos-2 with the conditioning passed as a prefix/anchor. Reweighting uses `w_stress = 1` for the conditional view since it is an explicit stress scenario by construction.

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
| `load_data(as_of_date, lookback_days)` | Aligned panel + covariates + regime labels from S3 | DataFrame handle (S3 URI) |
| `run_baseline_mc(panel, horizon, n_paths)` | Parametric joint scenarios (no covariates) | Paths handle |
| `run_chronos2(panel, horizon, n_paths, covariates?, conditioning?)` | Chronos-2 joint forecast (zero-shot) | Paths handle |
| `blend_paths(parametric_paths, chronos_paths, regime_features)` | Reweighting / regime augmentation | Weighted paths handle |
| `price_book(book_id, paths, weights)` | XCCY exposure → EE/PFE/ES | Metrics + per-time-bucket tensor |
| `plot(spec)` | Renders fan charts, PFE overlays, regime ribbons | Image S3 URI |
| `lookup_use_case(topic)` | Curated knowledge for the closing tour | Markdown brief |

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

- **Headline metric (for the room):** delta in 97.5% PFE between baseline and augmented runs in the chosen stress window, expressed in percent and notional dollars on the demo book. One number on the title slide.
- **Quant-defensible diagnostics (for the technical Q&A):**
  - **Regime-conditional coverage:** in held-out stress windows, what fraction of realized P&L outcomes fall outside the parametric 97.5% PFE band vs. the augmented band? Augmented should track closer to nominal coverage.
  - **Joint-tail dependence:** empirical vs. parametric vs. Chronos-2 tail correlation on held-out data (e.g., exceedance correlation between rates and FX in the bottom 5% region).
  - **Distribution sanity:** KS or energy-distance between path-set marginals and held-out empirical, by regime.
- **Operational metrics (for the platform Q&A):** end-to-end latency (data → blended PFE), Chronos-2 endpoint p50/p95 latency, scenario throughput.

All three are computed once and **pinned** for the demo so headlines do not drift between dry-runs and live presentations. They are also accessible via a "diagnostics" view the agent can summon if asked.

## 9. AWS Footprint

| Component | Service | Notes |
|---|---|---|
| Front-end | Amplify Hosting | Cloudscape React SPA |
| API | API Gateway + Lambda authorizer | Demo-grade API key; Cognito-swappable |
| Agent | Bedrock AgentCore | Claude (Sonnet-class default); CloudWatch traces |
| Data tool | Lambda | Reads S3 panel + covariates |
| Baseline MC | ECS Fargate task | Python (numpy/scipy); on-demand |
| Chronos-2 | SageMaker real-time endpoint | One ml.g5.xlarge (or similar); stoppable between demos |
| Blend / pricing | Lambda | Pure Python; vectorized over paths |
| Plotting | Lambda | matplotlib → S3 PNG; FE renders the URI |
| Storage | S3 | Panel, covariates, regime labels, sample book, plots, traces |
| Observability | CloudWatch Logs + X-Ray | AgentCore tool traces |
| IAM | Per-tool least-privilege roles | Standard |

**Cost shape:** dominated by SageMaker endpoint when running. Stop between demos. Single-region (us-east-1).

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
- More than one portfolio (the XCCY book) and one factor universe (FX + G10 rates) in the live demo.
- Production-grade model risk documentation (we gesture at it; we do not write the validation report).
- Full SR 11-7-style backtest harness; we have just enough diagnostics to defend the headline.
- Mobile, offline, multi-tenant.
- Regulatory artifacts (FRTB capital, BCBS-mandated stress tables).
- Intraday data and long (multi-decade) context windows in the live demo — these appear only in the closing tour.

## 12. Risks & Open Questions

- **Chronos-2 quality on the joint FX+rates universe is the single biggest unknown.** Mitigation: test on a held-out 2022 window during build, *before* committing the demo narrative. If it does not beat parametric materially in stress, reframe the story (still useful, but show what it does demonstrate honestly).
- **Same-lookback calibration may favor one engine for some regimes.** Mitigation: pre-pick the as-of dates so the comparison is honest; document selection criteria.
- **Reweighting could be argued as cherry-picking.** Mitigation: weights are deterministic functions of the regime detector; show the function.
- **Covariate asymmetry (Chronos-2 sees VIX/MOVE/WTI; parametric does not)** is an honest disadvantage for the parametric baseline. Mitigation: explicitly call this out as part of the value story — "this is something Chronos-2 can do that classical PCA + parametric cannot, without rebuild."
