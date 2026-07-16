---
marp: true
theme: gaia
paginate: true
backgroundColor: #fff
color: #1a1a2e
header: 'Chronos-2 / Numerix - Demo-first PoC'
---

<!-- _class: lead -->

# Chronos-2 / Numerix

## A live copilot for stress-aware exposure scenarios

**Flow:** demo first, details second

<!-- presenter note: Start in the app quickly. This deck is for a non-quant presenter with a mixed audience of quant experts and partner leaders. -->

---

## Let's Start With The Demo

What you will see:

1. Ask the copilot to run the exposure workflow.
2. Watch the Tool trace panel light up as it calls market data, Monte Carlo, Chronos-2, blend, price, and plot tools.
3. See the regime ribbon, PFE overlay chart, and EE / PFE / ES table.
4. Ask a natural-language what-if and watch the agent re-run the tools.

**Presenter line:** "I am going to show the working system first, then explain what happened under the hood."

<!-- presenter note: Switch to the live app here. Use the exact prompt in demo-first-presenter-script.md. -->

---

## The Plain-English Story

Banks and risk platforms run many future market scenarios to estimate exposure.

The question in this PoC:

> Can Chronos-2 act as a second, stress-aware scenario lens without replacing the existing Monte Carlo workflow?

The answer we demonstrate:

> Yes. It runs alongside the baseline, then the system blends the scenario sets and prices the same book with the same downstream code.

---

## What The App Is Doing

```text
Market data
  -> deterministic regime ribbon
  -> baseline Monte Carlo
  -> Chronos-2 scenario generation
  -> stress-aware blending
  -> same pricing and exposure code
  -> PFE chart + EE / PFE / ES summary
```

The important business point:

**Chronos-2 augments the risk workflow. It does not replace Numerix or the established pricing engine.**

The Tool trace panel shows this sequence live while the agent runs it.

---

## Why This Matters

For quant experts:

- Keeps the baseline Monte Carlo path intact.
- Uses transparent stress weights.
- Leaves pricing and exposure code unchanged.

For partner and alliance leaders:

- Shows a concrete AWS + Numerix co-build pattern.
- Demonstrates an AI-assisted workflow, not just a model benchmark.
- Opens adjacent use cases: stress testing, margin forecasting, market data gap filling.

---

## The Key Idea: "Second Lens Under Stress"

Baseline Monte Carlo is fast, familiar, and auditable.

Chronos-2 adds a second lens that can incorporate stress signals like:

- VIX
- MOVE
- WTI
- recent cross-asset behavior

The demo is about using that second lens where stress behavior matters most.

<!-- presenter note: Avoid saying the baseline is bad. Say it is the trusted core and Chronos-2 adds a stress-aware augmentation layer. -->

---

## What Changes In The Result

The system compares:

- **Baseline:** traditional parametric Monte Carlo paths.
- **Augmented:** baseline plus Chronos-2 paths blended by a stress signal.

The regime ribbon shows when the selected window is stressed.
The chart shows whether the augmented view lifts or reshapes the tail exposure.
The summary table shows EE, PFE, and ES as final-date numbers.

**Simple explanation:** "The blue line is what changes when the stress-aware scenario lens is included."

---

## Live Demo Delta

The stage-safe demo uses 500 paths per engine so it can finish live.

The app generates the regime ribbon, baseline, augmented result, chart, and delta live.

Verified live demo result:

| Metric | Baseline | Augmented | Change |
|---|---:|---:|---:|
| Terminal PFE 97.5% | $4.90M | $5.35M | +9.08% |

Live demo settings:

- As-of date: `2022-09-30`
- Paths: `500` per engine
- Stress weight: `0.5305`
- Baseline PCA components: `5`

<!-- presenter note: Use the app-generated values on this slide. Then point to the 5,000-path artifact as the higher-path reference run. -->

---

## 5,000-Path Reference Artifact

Measured against the live Chronos-2 endpoint:

| Metric | Baseline | Augmented | Change |
|---|---:|---:|---:|
| PFE 97.5% | $5.61M | $6.63M | +18.3% |

Scope:

- Artifact: `docs/results/headline_calibration.json`
- Endpoint: `chronos2-demo-ep`
- As-of date: `2022-09-30`
- PoC sample book, one measured stress window
- Directional evidence, not a production risk number

<!-- presenter note: If challenged, show the JSON artifact. Say the caveat out loud. Do not present this as a production-calibrated number. -->

---

## What "PFE" Means Here

For a mixed audience:

**PFE means Potential Future Exposure.**

It is a high-end estimate of how much a counterparty could owe us in a future market scenario.

In this PoC, the important point is not the acronym. The important point is:

> Stress-aware scenarios can change the tail of the exposure estimate.

---

## Live Architecture In One Slide

```text
Cloudscape SPA
  -> CloudFront + WAF streaming edge
  -> AgentCore runtime and gateway
  -> 9 tools
  -> ECS Fargate scenario jobs
  -> SageMaker / AutoGluon Chronos-2 endpoint
  -> S3 and DynamoDB artifacts
```

Why this matters:

- The demo is live on AWS.
- Long-running scenario jobs stream progress back to the browser.
- The same tool path supports chat and what-if exploration.

---

## What This Is And Is Not

This is:

- A working PoC.
- A demo of "augment, not replace."
- A live agentic workflow over risk tools.
- A good partner conversation starter.

This is not:

- A production risk engine.
- A regulatory approval claim.
- A multi-window backtest.
- A replacement for Numerix pricing or model governance.

---

## Partner Takeaway

This PoC gives Numerix and AWS a practical joint story:

1. Keep the existing risk platform.
2. Add a foundation-model scenario lens.
3. Make scenario exploration conversational.
4. Validate the lift through backtesting and model governance.

**Closing line:** "The value is not replacing the risk engine. The value is adding a stress-aware lens that a risk team can inspect, question, and eventually validate."

---

<!-- _class: lead -->

# Discussion

What would you need to see before trusting this beyond a PoC?
