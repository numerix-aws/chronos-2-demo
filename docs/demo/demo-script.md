# Presenter Script — Chronos-2 × Numerix PFE/XVA Augmentation PoC

> **This is the single consolidated presenter script** (the former separate demo-first script and slides have been merged in). The flow is **presenter first, demo second**: walk the slides (`docs/demo/slides.md`) to explain the mechanism, then run the live demo, then close.
>
> **How to use this script.** Read it as a teleprompter. The **SAY:** blocks are verbatim — you can read them word for word and sound credible. **DO / SHOW:** are stage directions (clicks, gestures, what to point at). **TRANSITION:** is the bridge sentence into the next slide.
>
> **Your audience is mixed:** quant experts, product stakeholders, and partner/alliance leaders. Quants know PFE, XVA, Monte Carlo, copulas, importance sampling cold — you do **not** need to teach them those concepts; you need to show that *this PoC respects them*. Lead with mechanism, not marketing. When in doubt, be more honest, not more impressive.
>
> **The rules that keep you safe** (full list at the bottom):
> 1. Never call this "production" or a "calibrated production risk number." It's a PoC sample book measured against the live endpoint.
> 2. You *can* cite the measured ~2,000× latency — but frame it as the structural closed-form-vs-nested-MC gap, not a tuned production SLA.
> 3. Never claim regulatory approval, and never say it "replaces" Numerix. It **augments**.
> 4. If a quant asks a deep question, answer simply and offer the exact mechanism. Do not bluff.
>
> If you forget everything else, the headline caveat is: **"measured live: +18.3% on the PoC sample book, as-of 2022-09-30 — a real endpoint result, but one window on a sample book, not a calibrated production number."** Say it out loud on Slide 12. Quants trust the honest version far more than a fragile precise claim.

## Run Of Show

Target length: 25 to 30 minutes.

1. Slides 1–15 (mechanism and architecture): 12 to 15 minutes.
2. Live demo (Slide 16 → app): 5 to 7 minutes.
3. Closing slides 17–20: 3 to 4 minutes.
4. Questions: remaining time.

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
"I'll keep the beats simple. We'll ask the copilot one natural-language question and watch it run the workflow through tools: load the cross-asset panel, show the regime detector lighting up under stress, run both engines — those are the async Fargate tasks — blend and price the book, and compare baseline against augmented PFE, EE, and ES. Then I'll ask a natural-language what-if — EUR rates down fifty basis points — and you'll watch the agent sequence the tools itself. The detailed walkthrough is scripted, so let me switch over."

**DO / SHOW:** Switch to the live SPA now and follow the "Live Demo" section below. Have the fallback (the committed calibration artifact in `docs/results`) ready in a second tab in case the endpoint is slow.

---
---

# Live Demo

## Live Demo Setup

Use the deployed app:

```text
https://main.d1ufy1thaj7uv6.amplifyapp.com
```

On first load, the app creates a demo session and stores it in localStorage using the deployed demo API key. There is no login flow in this PoC. Wait for the brief `Connecting to the demo copilot...` status to disappear before typing.

If the app shows `Connection failed` during prep, use the runbook's API key setup flow. Do this before the meeting, not on stage.

As a manual fallback, open DevTools on the app page and run this after replacing `<demo API key>`:

```javascript
localStorage.setItem(
  "chronos2-demo-session",
  JSON.stringify({ sessionId: crypto.randomUUID(), apiKey: "<demo API key>" }),
);
location.reload();
```

Known live endpoints from the current deployment:

```text
API_URL    = https://gulhcvbva4.execute-api.us-east-1.amazonaws.com/prod/
STREAM_URL = https://d1jp01nk04lrmo.cloudfront.net/
Chronos-2  = chronos2-demo-ep
```

## Pre-Demo Health Check

Do this before the presentation:

1. Open the app URL.
2. Confirm the page title contains `Numerix` and `Chronos-2`.
3. Wait 3 to 5 seconds after the page loads so the conversation panel can finish its initial session read.
4. Type a quick low-cost prompt:

```text
Say hello and confirm the Chronos-2 demo copilot is reachable. Do not run tools.
```

5. Confirm the assistant streams a response.
6. Do not start the full scenario run until you are ready to demo.

## Demo Step 1 - Start In The App

Switch from Slide 16 to the browser.

SAY:

"This is the live demo app. It is a Cloudscape front end connected to the AgentCore copilot we just looked at. I will ask one natural-language question, and the copilot will run the workflow through tools."

"For the live walkthrough, I am using 500 paths so the run finishes in a stage-safe window. We will generate the baseline and augmented result live in the app, then I will point to the committed 5,000-path artifact as the higher-path reference run."

DO:

Wait 3 to 5 seconds after the browser page loads before sending the first prompt. This avoids racing the app's initial conversation read.

Paste this exact prompt into the chat:

```text
Run the stage-safe headline demo for September 30, 2022. Use five years of trading history, project one trading year into the future, and generate 500 scenarios with each engine. Apply a 53.05% stress weight. Show the market regime and compare baseline exposure with Chronos-2-augmented exposure. Report the final EE, 97.5% PFE, 97.5% ES, and the PFE change.
```

Click Send.

SAY WHILE IT STARTS:

"The agent is now planning and calling tools. The important thing to watch is not just the answer, but the sequence: load the market data, show the regime ribbon, run the baseline Monte Carlo, run Chronos-2, blend the scenario sets, price the book, then plot the result."

Point briefly to the Tool trace panel:

"This panel is the stage view of the agent workflow. It is not a decorative progress bar; it is driven by the tool sequence the agent is executing."

## Demo Step 2 - Narrate The Wait

When the scenario jobs are running, do not stand silently.

SAY:

"Two of the steps are real compute jobs. They run as asynchronous Fargate tasks, so the agent launches them and polls until they are ready. That is why this takes longer than a simple chatbot response. We are asking it to run the scenario workflow, not just summarize text."

Timing note: the verified 500-path live run completed in about 3 minutes. If the run goes beyond 4 minutes, move to the fallback calibration result and come back to the browser when it finishes.

Fill the wait with the mechanism (this is where the architecture explanation earns its keep):

"The baseline is doing its PCA-Hull-White-GBM Cholesky draw. Chronos-2 is hitting the serverless SageMaker endpoint and getting back per-series quantile curves — and then, client-side, we're doing the inverse-CDF sampling and the lookback Gaussian copula to rebuild the joint tensor. The reason it's Fargate and not a plain Lambda is that the AutoGluon dependency is too heavy for a Lambda layer — so we bundle it in a container and run it as a task."

Plain-English version for the mixed audience:

"The baseline path is the familiar Monte Carlo view. Chronos-2 is the second scenario lens. The regime ribbon shows why the selected window is a stress window. The blend step decides how much weight to give that second lens under stress. Then the same pricing code computes the exposure chart and the EE, PFE, and ES summary."

If a quant asks what Chronos-2 returns:

"Chronos-2 returns per-series quantile curves. The code reconstructs joint paths client-side using inverse-CDF sampling and a lookback Gaussian copula. The endpoint does not directly emit joint paths."

## Demo Step 3 - Point At The Output

When the regime ribbon, chart, and exposure summary appear:

SAY:

"This is the payoff. The regime ribbon shows the stress score for the selected window. The exposure overlay shows the weighted-percentile PFE profile over time, and the table gives us the final EE, PFE, and ES numbers for baseline versus augmented."

If the chart shows baseline and augmented lines:

"The exact values depend on the run settings, but the interpretation is simple: the augmented line includes the Chronos-2 stress-aware path set. If it moves higher in the tail, that is the signal this PoC is designed to examine."

Point at the exposure summary table:

"For the presenter view, this table is the simplest readout. EE is the average exposure, PFE is the high-percentile tail number, and ES is the average beyond that tail threshold."

For the verified 500-path live demo run, the app-generated result was:

```text
Baseline terminal PFE 97.5%  = $4.90M
Augmented terminal PFE 97.5% = $5.35M
Absolute lift                = +$445K
Percent lift                 = +9.08%
```

Use this as the live demo headline. The 5,000-path artifact (Slide 12's +18.3%) is the higher-path reference run.

Live demo settings, if asked:

- As-of date: `2022-09-30`
- Paths: `500` per engine
- Stress weight: `0.5305`
- Baseline PCA components: `5`

If the live chart is flat or visually subtle:

"The live run proves the orchestration path end to end and gives us an app-generated delta. For the higher-path reference run, I will point to the committed 5,000-path artifact in the repo."

Do not overclaim:

"This is a PoC sample book, not a production risk number."

## Demo Step 4 - Natural-Language What-If

For the staged demo, use the chat rather than the What-if panel. The panel stays in the app as a playground for follow-up exploration, but the live presentation should show the agent translating a business-language stress into tool calls.

DO:

Paste this exact prompt into the chat:

```text
What happens to exposure if EUR rates fall 50 basis points across the two-, five-, and ten-year tenors for the first 30 business days? Use the same stage-safe setup as the headline demo, compare baseline exposure with the conditional Chronos-2 augmentation, and show the resulting exposure profile and final EE, 97.5% PFE, and 97.5% ES.
```

SAY:

"This is the conversational part of the demo. I am not filling out a form or reciting implementation fields. I am asking a scenario question, and the agent translates it into the tools for data, baseline, conditional Chronos-2, blending, pricing, and plotting."

While it runs:

"A 50 basis point EUR-rates move is easier for this audience to reason about than an arbitrary FX level shift. It touches the rates block directly, it maps cleanly to the EUR two-, five-, and ten-year series, and it makes the conditional scenario feel like a real risk-manager question. The conditioning matters here: the EUR-rates shift flows into Chronos-2 as covariate context, which is exactly the signal the parametric baseline structurally can't see."

When the what-if output appears:

"Now we have the exposure profiles side by side again, but this time the Chronos-2 path set was conditioned on an explicit EUR-rates stress. The chart is the weighted-percentile PFE profile; the table gives the final EE, PFE, and ES readout."

## Demo Step 5 - Adjacent Use Cases

If there is time after the chart:

DO:

Ask:

```text
What other Numerix workflows could Chronos-2 augment?
```

SAY:

"This last question is for partner leaders. The point is not only this one PFE workflow. The same pattern can apply to stress testing, margin forecasting, market data gap filling, and scenario-based limits monitoring."

## Fallback If The Live Run Is Slow

Use this if the scenario run takes too long or the room is losing patience.

SAY:

"This is a real scenario run, and the compute jobs can take a few minutes. Rather than make everyone watch a spinner, I am going to use the recorded calibration result from the same live endpoint and then come back to the app when it finishes."

Then cite the recorded calibration artifact:

```text
Baseline PFE 97.5%  = $5.61M
Augmented PFE 97.5% = $6.63M
Change              = +18.3%, about +$1.03M
As-of date          = 2022-09-30
Endpoint            = chronos2-demo-ep
Source              = docs/results/headline_calibration.json
```

DO:

If you want to make the artifact tangible, briefly show:

```text
docs/results/headline_calibration.json
```

SAY THE CAVEAT:

"This is a real live-endpoint measurement, but it is one PoC sample book and one measured stress window. It is directional evidence, not a production-calibrated risk number."

Never apologize at length or fumble. One sentence, switch to the fallback, keep the narration going. The mechanism is the same whether the paths are live or frozen — say that.

**TRANSITION (after demo, back to slides):** "So that's the system working end to end. Let me close by being very precise about what this is — and what it isn't."

---
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
"To leave you with the one-liner: correct and reweight — augment the tails, keep the pricing code. Chronos-2 gives us a stress-aware scenario lens beside the existing Monte Carlo workflow; the value is not replacing the risk engine, it's showing where a different view of the future may change tail exposure, then validating that carefully. Thank you. What have I got wrong, or what would you want to see before you'd trust the number?"

**DO / SHOW:** Invite questions openly. Use the Anticipated Q&A sections below. If you don't know something, say "I don't know — let me follow up" rather than bluffing. With this audience a confident bluff is the only way to actually lose them.

---
---

## A) Anticipated Q&A — quant experts

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

**Q13. "Why use Fargate instead of Lambda for the heavy jobs?"**
The baseline and Chronos-2 jobs are longer-running containerized workloads, and the Chronos-2 path includes AutoGluon dependencies that are too heavy for a simple Lambda layer.

---

## B) Anticipated Q&A — partner / alliance leaders

**Q: What is the business value?**
It shows how AWS can add AI-assisted scenario exploration to an existing risk workflow without forcing a platform replacement.

**Q: Why is this relevant to Numerix?**
Numerix owns trusted pricing and risk workflows. This PoC shows how Chronos-2 can augment scenario generation and interactive what-if exploration around that workflow.

**Q: What should happen next?**
Backtest across many dates and stress windows, broaden the book, harden governance, and define a partner-ready joint demo or offer.

**Q: How should we position this externally?**
As a PoC for stress-aware scenario augmentation, not as a production risk engine.

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

**Words to use**
- "Augment"
- "Second scenario lens"
- "Stress-aware view"
- "Same downstream pricing code"
- "Directional PoC result"
- "Validation and governance are next"

### Things to NEVER say / overclaim
- ❌ Don't call it **"production"** or a **"calibrated production risk number."** It's a PoC sample book.
- ✅ **Do** cite the measured **~2,000×** — but always as the structural closed-form-vs-nested-MC gap, never as a production SLA.
- ❌ Don't claim **regulatory approval or compliance** (FRTB / SA-CCR / IMM). It's a human-in-the-loop challenger.
- ❌ Don't say it **"replaces"** Numerix / the parametric model. It **augments** — runs alongside, never instead.
- ❌ Don't say Chronos-2 **"outputs joint paths."** It outputs **per-series quantiles**; *we* reconstruct the joint tensor.
- ✅ Cite **+18.3%** (live, as-of 2022-09-30, 5,000 paths), but always pair it with "PoC sample book, one window — directional, not a calibrated production number." The stage-safe 500-path live run is **+9.08%**.
- ❌ Don't claim the **Gaussian copula captures tail dependence.** Be honest: it couples marginals; richer copulas are roadmap.
- ❌ Don't promise **"guaranteed lift"** or say the **"model is validated."** Multi-window backtesting is the next step.
- ✅ When unsure, say **"I don't know — let me follow up."** With quants, that beats a confident bluff every time.
