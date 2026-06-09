# Presenter Script — Chronos-2 × Numerix PFE/XVA Augmentation PoC

> **How to use this script.** Read it as a teleprompter. The **SAY:** blocks are verbatim — you can read them word for word and sound credible. **DO / SHOW:** are stage directions (clicks, gestures, what to point at). **TRANSITION:** is the bridge sentence into the next slide.
>
> **Your audience are quant experts.** They know PFE, XVA, Monte Carlo, copulas, importance sampling cold. You do **not** need to teach them those concepts — you need to show that *this PoC respects them*. Lead with mechanism, not marketing. When in doubt, be more honest, not more impressive.
>
> **The three rules that keep you safe** (full list at the bottom):
> 1. Never call this "production" or a "calibrated production risk number." It's a PoC sample book measured against the live endpoint.
> 2. You *can* cite the measured ~2,000× latency — but frame it as the structural closed-form-vs-nested-MC gap, not a tuned production SLA.
> 3. Never claim regulatory approval, and never say it "replaces" Numerix. It **augments**.
>
> If you forget everything else, the headline caveat is: **"measured live: +18.3% on the PoC sample book, as-of 2022-09-30 — a real endpoint result, but one window on a sample book, not a calibrated production number."** Say it out loud on Slide 12. Quants trust the honest version far more than a fragile precise claim.

---

## Slide 1 — Title

**SAY:**
"Thanks everyone. What I want to show you today is a proof-of-concept we built with Numerix's framework in mind — using Amazon's Chronos-2 time-series foundation model to *augment* a hybrid Monte Carlo engine for PFE and XVA, specifically under stress. I'll be upfront from the first slide: this is still a PoC — a sample book, not a calibrated production system — but the headline number you'll see is an actual measurement against the live Chronos-2 endpoint, not a mock. So I'm going to lead with the mechanism — how it actually works — and I'll flag the scope: it's one as-of window on a sample book, not a multi-window-backtested production result."

**DO / SHOW:** Title slide up. Make eye contact, don't rush. Set the "this is honest engineering, not a sales pitch" tone here — it buys you credibility for the whole talk.

**TRANSITION:** "Let me start with the problem we're actually trying to solve, because it's a specific one — not 'Monte Carlo is bad.'"

---

## Slide 2 — The problem: exposure under stress

**SAY:**
"Parametric Monte Carlo is the workhorse for exposure, and for good reason — it's fast, it's transparent, and it's auditable. We are not here to argue against it. But it has three known weak spots under stress. First, joint-tail mis-calibration: a Gaussian-copula or Cholesky structure tends to understate co-movement out in the far tail. Second, correlation breakdown — a static factor covariance just can't represent rates-FX or equity-credit correlation flipping during a crisis. And third, no exogenous signal: things like VIX, MOVE, and WTI carry forward-looking stress information, but you cannot feed them into a PCA-plus-parametric model without re-specifying the factor model itself. So the question we asked is not 'how do we replace MC' — it's 'can we add a calibrated correction exactly where parametric MC is weakest?'"

**DO / SHOW:** Point at each of the three bullets as you hit them. Linger on the third — the covariate point is the spine of the whole talk.

**TRANSITION:** "That framing — a targeted correction, not a replacement — is the entire thesis. Here it is in one sentence."

---

## Slide 3 — The thesis: "correct + reweight"

**SAY:**
"Here's the thesis stated precisely: Chronos-2 augments — does not replace — the parametric Monte Carlo, by capturing joint-tail dynamics and regime-driven correlation breakdown, while the *same* downstream pricing and exposure code consumes either path set. Mechanically there are four moves. Both engines produce path sets in the same tensor contract. A deterministic regime detector emits a stress weight, w-stress, between zero and one. A blender importance-weights the paths. And — this is the part people miss — Chronos-2 always runs *alongside* the baseline, never instead of it. In calm markets the baseline dominates; we only lean on Chronos-2 where the stress signal says to."

**DO / SHOW:** Read the blockquote thesis slowly and verbatim — it's the load-bearing sentence of the deck. Then tick the four bullets on your fingers.

**TRANSITION:** "Let me give you the whole pipeline at ten thousand feet, and then we'll walk each box."

---

## Slide 4 — Architecture at 10,000 ft

**SAY:**
"The shape is: dual engines, into a regime detector, into a blender, into one shared pricing engine. The key invariant — and I'd ask you to hold onto this — is that the *only* thing that ever changes downstream is the input path set going into pricing. Engine one is the parametric baseline: PCA plus Hull-White plus GBM. Engine two is Chronos-2, which gives us quantiles that we turn into joint paths. The detector turns three deterministic features into w-stress. The blender does importance weighting with a tail-and-body split. And pricing is one closed-form exposure engine that will happily take any of three inputs — baseline-only, Chronos-only, or blended — without knowing the difference."

**DO / SHOW:** Trace the app-flow diagram left to right with your hand: engines → detector → blender → pricing. Physically point at the single arrow into pricing when you say "only the input path set changes."

**TRANSITION:** "Let's start at the left. Engine one — the parametric baseline you already know well."

---

## Slide 5 — Engine 1: parametric baseline

**SAY:**
"Engine one is a conventional joint sampler, and it's deliberately covariate-blind. We run PCA on daily returns to get principal factors, Hull-White one-factor dynamics for the short rate, GBM-style evolution for FX, and we draw them jointly via the Cholesky of the factor covariance. Output is a PathSet with shape n-paths by horizon by n-series. This is our reference engine — fast, well-understood, fully auditable. And I want to be explicit: it does *not* ingest VIX, MOVE, or WTI. That blindness is intentional, and the next two slides are about why."

**DO / SHOW:** Point at the code box (returns → PCA → HW/GBM → Cholesky → PathSet). Keep this slide brisk — this audience knows these methods; you're establishing that the baseline is honest and standard, not novel.

**TRANSITION:** "Now engine two, which is where the foundation model comes in — and there's an important subtlety about *what it actually returns.*"

---

## Slide 6 — Engine 2: Chronos-2 foundation model

**SAY:**
"Chronos-2 is served as a serverless AutoGluon Cloud endpoint, and here's the subtlety: it returns per-series *quantile curves*, not sample paths. So we reconstruct the joint tensor client-side, in three steps. One, inverse-CDF marginal sampling per series from its quantile curve. Two, a lookback Gaussian copula couples those marginals across series, so we preserve the realized cross-correlation from the window. Three, out comes the same n-paths by horizon by n-series PathSet, so it's a drop-in. And the headline capability: Chronos-2 ingests the exogenous covariates — VIX, MOVE, WTI — zero-shot, with no factor re-fit."

**DO / SHOW:** Emphasize "quantile curves, not sample paths" — slow down. This is the precision point a sharp quant will test you on. Do **not** imply the model emits joint paths directly; the joint structure is reconstructed by us.

**TRANSITION:** "So you've got two engines that differ in one deliberate way. Let me put that asymmetry on one slide, because it *is* the value proposition."

---

## Slide 7 — The asymmetry, and why it's the point

**SAY:**
"Here's the asymmetry side by side. Both engines produce joint paths — the baseline via Cholesky, Chronos-2 via inverse-CDF plus the lookback copula. But on ingesting VIX, MOVE, WTI: the baseline is a 'no,' Chronos-2 is a 'yes, zero-shot.' And to add a new covariate, the baseline needs a re-specify-and-re-fit; Chronos-2, you just feed it in. I want to be clear this is not a defect of the baseline that we're exploiting unfairly — it's a structural property of factor models. The two engines are *meant* to disagree precisely where stress signals matter. That disagreement, captured and weighted, is the correction we're adding."

**DO / SHOW:** Walk the three table rows top to bottom. Pause on the "Add a new covariate" row — "re-specify and re-fit" vs "feed it in" is the line that lands with quants who've maintained a factor model.

**TRANSITION:** "If we're going to lean on Chronos-2 only when stress warrants it, you need to trust *how* we decide a regime is stressed. So let's open up the detector — it's deliberately not a black box."

---

## Slide 8 — Regime detector: deterministic, not a black box

**SAY:**
"The regime detector is fully deterministic — there is no fitted model here, by design. We take three features over a trailing window: rolling volatility, FX-rates correlation, and vol-of-vol. Each one is percentile-ranked *within its own history*, and then we average the three ranks. That gives w-stress, between zero and one. Zero means calm, so trust the parametric engine; one means stress, so lean toward Chronos-2. Our default stress-label threshold is 0.7. The whole point is that it's inspectable and reproducible — an auditor can see exactly why a given date scored as stressed, feature by feature. There's no parameter we tuned to make a number look good."

**DO / SHOW:** Point at the three features, then at the averaging formula. Stress "percentile-ranked within its own history" and "no fitted model" — this preempts the "isn't w_stress just another fitted parameter" question coming in Q&A.

**TRANSITION:** "Once we have w-stress, the blender uses it to reweight paths. This is textbook importance sampling — let me show you exactly how."

---

## Slide 9 — Blender: importance weighting

**SAY:**
"The blender is standard importance sampling, and the rule I want you to hold is: every path keeps a non-zero weight — we never delete paths. The steps: per engine, compute terminal portfolio P&L across all paths; mark the top and bottom five percent as the tail, the rest is the body; assign weights, normalize each engine to sum to one, then combine the two engines fifty-fifty. In the tail, the parametric engine gets one-minus-w-stress and Chronos-2 gets w-stress — so under stress the tail tips toward Chronos-2. In the body it's a fixed ninety-ten split, parametric-heavy, which keeps the augmentation *visible* even in calm markets rather than vanishing to zero. And PFE, EE, ES then become weighted percentiles over the combined set."

**DO / SHOW:** Point at the weight table. Trace the tail row — "1 minus w-stress" for parametric, "w-stress" for Chronos — then the body row. Emphasize "no paths deleted" and "weights normalize to one" — that's your defense against the double-counting question.

**TRANSITION:** "And because all of that just produces a reweighted PathSet, the pricing engine downstream doesn't change at all. That's what makes 'drop-in' literal."

---

## Slide 10 — Shared pricing / exposure engine

**SAY:**
"One code path, three possible inputs. The only thing that changes is which PathSet goes in — parametric-only, Chronos-only, or blended. We do closed-form valuation for cross-currency swaps, equity forwards, and CDS protection. Exposure metrics — EE, PFE, ES — are computed as weighted percentiles over the input paths. And critically, there is *no* nested Monte Carlo revaluation in the hot path; it's closed-form factor-model pricing. That's what makes the drop-in claim literal: the downstream stack genuinely does not know, and does not need to know, which engine produced the paths."

**DO / SHOW:** Point at the code box (PathSet any source → FM repricing → weighted EE/PFE/ES). Emphasize "no nested MC in the hot path" — it sets up Slide 13.

**TRANSITION:** "Now, the whole reason this is interesting is cross-asset behavior — let me show you the universe we ran and what Chronos-2 captures that the baseline structurally can't."

---

## Slide 11 — Cross-asset value, captured zero-shot

**SAY:**
"The factor universe is twenty-one series across four blocks: rates — USD, EUR, JPY, GBP at the 2-, 5-, and 10-year points; five major FX pairs; two equity indices, SPX and Nikkei; and two credit series, US investment-grade and high-yield OAS. The claim here is specific: Chronos-2 captures joint rates-FX correlation breakdown and equity-credit co-tail behavior zero-shot — no per-scenario fitting. The parametric PCA baseline cannot represent those regime shifts without re-fitting the factor model. So this isn't 'our model is smarter' — it's that a foundation model conditioned on stress covariates can express joint-tail structure that a static covariance, by construction, holds fixed."

**DO / SHOW:** Point at the four blocks of the table. When you say "zero-shot," make sure you've already defined it (it's on the cheat-sheet) — it means no task-specific fitting, the model wasn't trained on this book.

**TRANSITION:** "So what does that buy us numerically? Here's the headline — and this is the slide where I'm going to be very careful about what I'm claiming."

---

## Slide 12 — Headline result, with the caveat

**SAY:**
"Measured against the live Chronos-2 endpoint, the 97.5% PFE goes from about 5.6 million on the baseline to about 6.6 million augmented — a plus-eighteen-percent move, about a million dollars, as-of September 30th 2022 in the rate-hike window, with w-stress around 0.53. The setup is five thousand paths per engine, a horizon of about twenty-one days, about twenty-one series. Now the honest part, and I want to say it plainly: **this IS a live-endpoint measurement, not a mock — but it's our PoC sample book on one as-of date, so treat it as directional evidence, not a calibrated production risk number.** Our regression test deliberately asserts only the *direction* — augmented is greater than or equal to baseline — and the order of magnitude. It does *not* pin an exact value, because pinning a single-window number to two decimals would be false precision. The takeaway is directional: under stress, the augmentation pushes PFE up, in the tail, where you'd expect a richer joint-tail model to."

**DO / SHOW:** This is the integrity moment of the talk. Say the caveat sentence out loud, unhurried, looking at the room. Do **not** round "+18.3%" into "a few percent" and do **not** oversell it as production — always pair the +18% with the sample-book / one-window scope. If anyone leans in skeptically, you've already disarmed them by volunteering the caveat.

**TRANSITION:** "While we're being precise about what we claim — let me address latency directly, because we measured it."

---

## Slide 13 — Nested-MC benchmark framing

**SAY:**
"There's a file in the codebase, nested_mc dot py, and I want to be clear about its status: it exists as a benchmark *reference* only — it is never wired into the production compute-metrics path. The production path uses closed-form factor-model pricing, which structurally avoids the expensive nested-MC revaluation — you're not running an inner simulation per outer path. We measured it: closed-form comes in around 0.28 seconds against nested-MC at about 550 seconds — call it 2,000×, across 480,000 revaluations. I want to frame that honestly: it's the *structural* gap between closed-form and nested MC — no inner simulation per outer path — so it's illustrative of the architecture, not a tuned production SLA. The point I am making is architectural: exposure comes from weighted percentiles over repriced paths, not from a nested inner simulation."

**DO / SHOW:** If asked for a number, cite the ~2,000× — but add: "that's the structural closed-form-vs-nested-MC gap, not a production SLA I'm committing to." Read the blockquote verbatim; it's worded carefully.

**TRANSITION:** "That's the quant core. Now the part that makes it usable for an analyst day-to-day — the agentic copilot."

---

## Slide 14 — The agentic copilot

**SAY:**
"We wrapped the whole pipeline in an Amazon Bedrock AgentCore copilot — a containerized Strands agent running on Claude Sonnet — that orchestrates nine tools exposed as MCP tools through the AgentCore Gateway. So an analyst can just ask, in plain English, 'what's my PFE if EUR rates sell off fifty basis points?', and the agent sequences the tools and conditions Chronos-2 on that scenario. The nine tools group into data tools, the two engine pairs, and the pipeline tools — blend, price, plot. Two of them, run-baseline-mc and run-chronos2, are asynchronous ECS Fargate tasks, so the agent launches them and polls. And it supports genuine end-to-end what-if conditioning — the series shifts and stress scenarios get passed through to Chronos-2, not just bolted on at the end."

**DO / SHOW:** Point at the tool table (Data / Engines / Pipeline). Mention the model is `us.anthropic.claude-sonnet-4-6` if asked specifically, but "Claude Sonnet" is fine for narration. Flag "async Fargate, launch and poll" — it explains the latency you'll cover during the live demo.

**TRANSITION:** "Underneath that copilot is real AWS infrastructure — here's the deployed shape, because it's live in our account right now."

---

## Slide 15 — AWS infrastructure

**SAY:**
"This is deployed live, and a few pieces are worth calling out. Streaming responses come over server-sent events through a CloudFront distribution with origin access control and SigV4, fronted by a WAF, sitting in front of a Lambda Function URL in response-stream mode. The REST API is API Gateway with an x-api-key authorizer. The agent is Bedrock AgentCore Runtime plus Gateway exposing the nine MCP tools. Compute for the two engines is ECS Fargate async workers. Chronos-2 itself is a serverless SageMaker AutoGluon endpoint. State is DynamoDB for sessions and S3 for snapshots and plot artifacts. And the front end is a Cloudscape single-page app on Amplify Hosting."

**DO / SHOW:** Walk the infra diagram following the request path: SPA → CloudFront/WAF → Function URL / API Gateway → AgentCore → Fargate + SageMaker → DynamoDB/S3. Keep it crisp; don't rat-hole on infra with a quant audience unless they ask. If someone asks why SSE goes through a Function URL instead of API Gateway: "API Gateway buffers the response and breaks streaming — a Function URL in response-stream mode is what actually streams tokens."

**TRANSITION:** "Enough architecture — let me show you the thing running."

---

## Slide 16 — Live demo

**SAY:**
"I'll keep the beats simple. We'll load the cross-asset panel and watch the regime detector light up under stress. We'll run both engines — those are the async Fargate tasks — and watch them complete. We'll blend and price the book, and compare baseline against augmented PFE, EE, and ES. Then I'll ask a natural-language what-if — EUR rates down fifty basis points — and you'll watch the agent sequence the tools itself. And finally we'll look at the weighted-percentile exposure profiles side by side. The detailed walkthrough is scripted, so let me switch over."

**DO / SHOW:** Switch to the live SPA now. Follow the detailed walkthrough section below. Have the fallback (pre-baked plots from the committed calibration run, `docs/results`) ready in a second tab in case the endpoint is slow.

**TRANSITION (after demo):** "So that's the system working end to end. Let me close by being very precise about what this is — and what it isn't."

---

## Slide 17 — What this is, and isn't

**SAY:**
"What it is: a working proof-of-concept of 'augment, not replace'; a transparent, auditable augmentation layer with deterministic weights; and a genuine drop-in to existing closed-form pricing and exposure code. What it isn't — and I'd rather you hear this from me: it is *not* a production system or a calibrated production risk number. The headline IS a live-endpoint measurement — but it's on a PoC sample book and a single as-of window, so it has *not* been multi-window backtested. And the ~2,000× latency is the *structural* closed-form-vs-nested-MC gap, not a tuned production SLA. I'd rather under-claim here and have the mechanism stand on its own."

**DO / SHOW:** Read both columns. Don't soften the "isn't" column — saying it crisply is what earns the room's trust.

**TRANSITION:** "Which leads naturally into what's next to turn this from a PoC into something you'd actually put in front of model risk."

---

## Slide 18 — Roadmap / next steps

**SAY:**
"Five things. Live-endpoint calibration and the latency benchmark are already done — we have one window measured, plus-eighteen-percent, and the ~2,000× structural latency gap. So the work ahead is: first and most important, multi-window backtesting — re-derive the PFE delta across many as-of dates and stress regimes, not just the single window we've measured. Second, broaden the book — more instruments, a larger factor universe, longer horizons. Third, production hardening — model governance, monitoring, SLAs. And fourth, validation against realized stress periods: coverage tests, tail-dependence diagnostics, distribution-distance checks. The diagnostics scaffolding for that last one already exists in the codebase — it's about pointing it at more live data."

**DO / SHOW:** Emphasize that the first item — live calibration — is the gate to everything else. This is where you'd invite collaboration if this is a partner conversation.

**TRANSITION:** "Let me pull the threads together with why this should matter to a quant specifically — not to a CTO, to you."

---

## Slide 19 — Why this matters to quants

**SAY:**
"Seven reasons, quickly. It's augmentation not replacement, so it drops into existing pricing code. The regime weights are transparent and deterministic — auditable, not opaque ML. The blending is textbook importance sampling — no paths discarded. There's a real covariate edge — VIX, MOVE, WTI zero-shot, which a PCA-plus-parametric model can't take without re-specification. It captures cross-asset joint-tail and correlation-breakdown structure zero-shot. It reduces reliance on nested MC for exposure. And the agentic UX makes what-if exploration genuinely conversational. The through-line: nothing here asks you to throw away a model you trust — it asks you to add a weighted correction exactly where that model is weakest, and to be able to audit every step."

**DO / SHOW:** Tick the points (a) through (g). End on the through-line sentence — slow down, it's your closing argument.

**TRANSITION:** "That's the PoC. I'd love your hardest questions — that's genuinely the most useful part for us."

---

## Slide 20 — Q&A / closing

**SAY:**
"To leave you with the one-liner: correct and reweight — augment the tails, keep the pricing code. Thank you. What have I got wrong, or what would you want to see before you'd trust the number?"

**DO / SHOW:** Invite questions openly. Use the Anticipated Q&A section below. If you don't know something, say "I don't know — let me follow up" rather than bluffing. With this audience a confident bluff is the only way to actually lose them.

---
---

## A) Live Demo Walkthrough — detailed narration

> **Goal:** show the agent loading data, running both engines async, blending under the current w_stress, pricing, and plotting — while you narrate over the latency. Keep talking through the async waits; never stand in silence watching a spinner.

### Step 0 — Before you click anything (have these ready)
- The Cloudscape SPA open and logged in (x-api-key already in the client).
- A **second browser tab** with pre-baked plots from the committed live calibration run (the PFE overlay and the regime ribbon) — your fallback.
- Know your fallback number cold: **baseline ≈ $5.6M, augmented ≈ $6.6M, +18.3%, live endpoint, as-of 2022-09-30, PoC sample book / one window.**

### Step 1 — Open the app, set the scene
**DO:** Bring up the Cloudscape SPA, chat panel on one side, charts area on the other.
**SAY:** "This is the analyst-facing app — Cloudscape front end, talking to the AgentCore copilot. Everything you'll see the agent do maps to one of the nine tools we just looked at."

### Step 2 — Type the natural-language what-if
**DO:** Type into the chat, verbatim:
> *"What's my PFE on the XCCY book if EUR rates sell off 50bps and equity vol spikes?"*
Hit send.
**SAY:** "I'm asking in plain English — no scenario IDs, no config files. The agent has to figure out the tool sequence itself."

### Step 3 — Narrate the agent's plan as tokens stream
**DO:** Point at the streaming tokens appearing in the chat (this is the SSE stream — CloudFront → Function URL → browser via fetch + ReadableStream).
**SAY:** "Notice the response is streaming token by token — that's server-sent events coming through CloudFront in front of a Lambda Function URL. The agent is laying out its plan: load the panel, launch both engines, blend, price, plot. Watch it call the tools in order."

### Step 4 — load_data fires
**SAY:** "First it calls load_data — pulling the cross-asset panel, our twenty-one series, and slicing it as-of the scenario date. The EUR-rates shift and the vol spike get encoded as the what-if conditioning."

### Step 5 — Both engines launch (the async wait — cover it)
**DO:** The agent calls `run_baseline_mc` and `run_chronos2`; both are async ECS Fargate launches, then it polls with `check_baseline_mc` / `check_chronos2`. There will be a wait here.
**SAY (fill the wait — this is where the architecture explanation earns its keep):**
"Both engines are launching right now as asynchronous Fargate tasks — the agent fires them off and polls for completion, so they run in parallel rather than blocking. The baseline is doing its PCA-Hull-White-GBM Cholesky draw. Chronos-2 is hitting the serverless SageMaker endpoint and getting back per-series quantile curves — and then, client-side, we're doing the inverse-CDF sampling and the lookback Gaussian copula to rebuild the joint tensor. The reason it's Fargate and not a plain Lambda is the AutoGluon dependency is too heavy for a Lambda layer — so we bundle it in a container and run it as a task. While that finishes — the conditioning matters here: the EUR-rates sell-off and the vol spike both flow into Chronos-2 as covariate context, which is exactly the signal the parametric baseline structurally can't see."
*(If still waiting:)* "And because Chronos-2 ingests VIX, MOVE, and WTI zero-shot, a vol spike like this is precisely the regime where the two engines should diverge — which is what the blender is about to exploit."

### Step 6 — blend_paths with current w_stress
**DO:** Agent calls `blend_paths`.
**SAY:** "Both path sets are back, in the same tensor shape. The regime detector has computed w-stress for this scenario — under a vol spike it'll be elevated — and the blender is importance-weighting: tail toward Chronos-2 by w-stress, body kept parametric-heavy, every path retained with a non-zero weight."

### Step 7 — price_book
**DO:** Agent calls `price_book`.
**SAY:** "Now the shared pricing engine reprices the cross-currency book — closed form, no nested MC — and produces EE, PFE, and ES as weighted percentiles over the blended set. Same code that would price the baseline-only paths."

### Step 8 — plot, and the payoff
**DO:** Agent calls `plot`; chart renders in the charts area — PFE overlay (baseline vs augmented) and the regime ribbon.
**SAY:** "And here's the payoff: the PFE profile with baseline and augmented overlaid, and the regime ribbon showing where w-stress flagged stress. You can see the augmentation lifting the tail in the stressed region — which is the directional result. I'll repeat the caveat: that lift is about eighteen percent on the 97.5 PFE — measured live, as-of September 30th 2022; it's our PoC sample book on one window, so directional, not a production number."

### Step 9 — (optional) point at the side-by-side profiles
**SAY:** "If you want, we can flip to the side-by-side weighted-percentile profiles — baseline, Chronos-only, and blended — so you can see how much of the move comes from the tail reweighting versus the body."

### Fallback plan (endpoint slow or unavailable)
**DO:** Switch to the second tab with pre-baked plots.
**SAY:** "The live endpoint's taking longer than I want to make you watch — let me show you the same result from our committed calibration run, which is what our regression test actually pins. Here's the PFE overlay and the regime ribbon from that run." Then narrate Steps 6–8 against the static images.
**SAY (the honest framing):** "These are from the committed live calibration run in `docs/results` — same pipeline, measured against the live endpoint. Baseline about 5.6 million, augmented about 6.6, plus eighteen percent on the 97.5 PFE, as-of September 30th 2022. Multi-window backtesting is exactly what's next on the roadmap."
> Never apologize at length or fumble. One sentence, switch to the fallback, keep the narration going. The mechanism is the same whether the paths are live or frozen — say that.

---

## B) Anticipated Q&A

> Answers are 2–4 sentences, defensible, honest. If a question goes past what you know, say "I'd have to check / follow up" — do not invent.

**Q1. "Isn't this just stacking two models — how do you avoid double-counting risk?"**
We're not summing two exposures; we're importance-weighting one combined path set. Each engine's weights normalize to sum to one, and we combine fifty-fifty, so the total probability mass is still one — there's no double count. It's a reweighting of *which* paths matter, not an addition of two risk numbers.

**Q2. "How is w_stress not just another fitted parameter?"**
It's deterministic — there's no fitting at all. It's the average of three percentile ranks of *observable* quantities — rolling vol, FX-rates correlation, vol-of-vol — each ranked within its own history. You can recompute it by hand from the data; nothing was tuned to hit a target, and an auditor can see exactly why any date scored where it did.

**Q3. "Why a Gaussian copula — doesn't that kill tail dependence?"**
Fair challenge, and I want to be honest about it. The Gaussian copula couples the *marginals* using the realized covariance from the lookback window — so the cross-dependence structure is Gaussian, that's a known limitation. But the fat tails live in the marginals, which come from Chronos-2's quantile curves, not from the copula. Richer copulas — t, or a vine — are explicitly on the roadmap; for a PoC we took the transparent baseline coupling and put the tail behavior in the marginals.

**Q4. "How do you validate Chronos-2's quantiles?"**
The diagnostics module has coverage and PIT checks — does the realized outcome fall in the predicted quantiles at the right frequency. In this PoC those run against the curated snapshot panel; proper backtesting against realized stress periods is on the roadmap and is the thing I'd want before trusting a calibrated number. I won't claim it's validated yet — it isn't.

**Q5. "What about backtesting and regulatory acceptance — FRTB, SA-CCR, IMM?"**
This is a proof-of-concept; we are explicitly *not* seeking model approval with it. It's positioned as a challenger / augmentation layer with a human in the loop, sitting next to the approved model — not as a replacement for an IMM or SA-CCR engine. Regulatory validation would come much later and is well outside this scope; I'd be overclaiming to suggest otherwise.

**Q6. "What's the cost and latency of running two engines?"**
The two engines run as async Fargate tasks in parallel, so it's not strictly additive in wall-clock, and pricing is closed-form so there's no nested-MC blowup. We measured it: closed-form about 0.28 seconds versus nested-MC about 550 seconds, roughly 2,000× — but that's the structural gap between the two approaches, not a tuned production SLA I'm committing to.

**Q7. "What if Chronos-2 disagrees wildly with the baseline?"**
Two things keep that contained. The w-stress gating means in calm regimes the tail stays baseline-dominant — Chronos only gets tail weight as stress rises — and the body keeps a fixed ninety-ten parametric-heavy floor. And the diagnostics flag divergence between the engines, so a wild disagreement is surfaced, not silently blended away. It can't quietly run away with the number.

**Q8. "Is the plus-eighteen-percent real?"**
Yes — it's a genuine live-endpoint measurement: +18.3% as-of September 30th 2022, committed in `docs/results`. The honesty is about *scope*: it's our PoC sample book on a single as-of window, so it's directional evidence, not a multi-window-backtested production number. Our regression test asserts only the direction and order of magnitude, not the exact value, precisely so we don't imply false precision. Broadening to many windows is the top item on the roadmap.

**Q9. "Why not just recalibrate the parametric model instead of adding a second engine?"**
Because the covariates can't enter the parametric model without re-specifying it. VIX, MOVE, WTI aren't factors in a PCA-plus-Hull-White setup — adding them means a new factor model, re-derivation, re-fit, re-validation. Chronos-2 conditions on them zero-shot, with no re-fit, which is the whole reason it's worth standing up alongside.

**Q10. "Data leakage or look-ahead in Chronos-2?"**
We slice the panel as-of the scenario date and the copula uses the lookback window only — no future data enters either the conditioning or the coupling. That as-of discipline is in the data layer. If you want to stress-test it, that's exactly the kind of thing the backtesting work on the roadmap would harden.

**Q11. "Why fifty-fifty between the engines, and why a five-percent tail cut-off?"**
They're deliberate, transparent defaults for the PoC, not fitted optima — fifty-fifty so neither engine is privileged a priori, and ±5% as a conventional tail definition. Both are parameters you'd calibrate during the live-calibration phase; nothing in the architecture depends on those exact values.

**Q12. "Does the same downstream code really consume either path set unchanged?"**
Yes — that's the core design invariant. Both engines emit the identical PathSet tensor — n-paths by horizon by n-series — plus weights, and the pricing engine takes that contract regardless of source. We test all three inputs — baseline-only, Chronos-only, blended — through the same compute-metrics path.

---

## C) Presenter cheat-sheet

> One-line plain-English reminders. Glance, don't read aloud.

**Exposure / risk terms**
- **PFE (Potential Future Exposure):** a high-percentile (here 97.5%) of possible future exposure — a worst-plausible-case "how much could they owe us."
- **EE (Expected Exposure):** the *average* exposure over the paths at each future time.
- **ES (Expected Shortfall):** the average loss *beyond* the tail cut-off — mean of the worst cases, not just a single percentile.
- **XVA:** the family of valuation adjustments (credit, funding, capital) layered on derivative prices; PFE feeds them.
- **XCCY swap (cross-currency swap):** exchange of interest/principal in two different currencies — sensitive to both rates and FX.
- **CDS protection:** a credit default swap leg — pays out if a reference entity defaults; here valued closed-form.
- **Hull-White:** a standard one-factor model for how the short interest rate evolves over time.
- **PCA factor model:** compresses many correlated series into a few principal "factors" that drive them.
- **Cholesky:** the matrix trick that turns independent random draws into *correlated* ones with a target covariance.

**Method terms**
- **Importance sampling:** reweight paths by how much they matter instead of throwing any away — weights sum to one.
- **Gaussian copula:** a way to glue separate marginal distributions into a joint one using a Gaussian correlation structure (couples the *marginals*; tails live in the marginals here).
- **Inverse-CDF sampling:** turn a uniform random number into a draw from a distribution by inverting its quantile curve — how we go from Chronos-2's quantiles to sample paths.
- **w_stress:** our deterministic 0-to-1 stress dial; average of three percentile-ranked observables; ≥0.7 = "stressed."
- **Zero-shot:** the model handles this task/data with no task-specific training or fitting — you just feed it in.

**Regulatory acronyms (you are NOT claiming compliance with any of these)**
- **FRTB:** Fundamental Review of the Trading Book — market-risk capital rules.
- **SA-CCR:** Standardized Approach for Counterparty Credit Risk — a regulatory exposure formula.
- **IMM:** Internal Model Method — a bank's own approved exposure model. *(We're a challenger to these, not approved by them.)*

### Things to NEVER say / overclaim
- ❌ Don't call it **"production"** or a **"calibrated production risk number."** It's a PoC sample book.
- ✅ **Do** cite the measured **~2,000×** — but always as the structural closed-form-vs-nested-MC gap, never as a production SLA.
- ❌ Don't claim **regulatory approval or compliance** (FRTB / SA-CCR / IMM). It's a human-in-the-loop challenger.
- ❌ Don't say it **"replaces"** Numerix / the parametric model. It **augments** — runs alongside, never instead.
- ❌ Don't say Chronos-2 **"outputs joint paths."** It outputs **per-series quantiles**; *we* reconstruct the joint tensor.
- ✅ Cite **+18.3%** (live, as-of 2022-09-30), but always pair it with "PoC sample book, one window — directional, not a calibrated production number."
- ❌ Don't claim the **Gaussian copula captures tail dependence.** Be honest: it couples marginals; richer copulas are roadmap.
- ✅ When unsure, say **"I don't know — let me follow up."** With quants, that beats a confident bluff every time.
