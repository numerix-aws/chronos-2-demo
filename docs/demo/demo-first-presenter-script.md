# Demo-First Presenter Script - Chronos-2 / Numerix PoC

This script is written for a presenter who is not a quant expert. The audience is mixed: quant experts, product stakeholders, and partner/alliance leaders.

Use this script with `docs/demo/demo-first-slides.md`. The old `docs/demo/demo-script.md` is still useful as a technical backup, but it is quant-first and explanation-first. This script is demo-first.

## What To Remember

If you remember only four things, remember these:

1. Chronos-2 augments the Monte Carlo workflow. It does not replace Numerix.
2. Start with the live demo, then explain what happened.
3. The headline +18.3% result is a live-endpoint calibration on a PoC sample book and one stress window. It is directional, not a production risk number.
4. If a quant asks a deep question, answer simply and offer the exact mechanism. Do not bluff.

## Run Of Show

Target length: 12 to 15 minutes.

1. Opening slide: 30 seconds.
2. Live demo: 5 to 7 minutes.
3. Plain-English explanation: 4 to 5 minutes.
4. What this means for Numerix and AWS: 2 minutes.
5. Questions: remaining time.

## Live Demo Setup

Use the deployed app:

```text
https://main.d1ufy1thaj7uv6.amplifyapp.com
```

The browser must already have a valid demo session in localStorage. There is no login flow in this PoC.

If the app is blank or the chat does not respond during prep, use the runbook's API key setup flow. Do this before the meeting, not on stage.

For a fresh browser profile, open DevTools on the app page and run this after replacing `<demo API key>`:

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

## Opening

Slide: title slide.

SAY:

"I am going to start with the working demo first, then I will explain the moving parts. The simple version is this: we are not replacing the existing Monte Carlo or Numerix-style pricing workflow. We are adding a Chronos-2 scenario lens beside it, then comparing how the stress-aware view changes exposure."

TRANSITION:

"Let me switch into the app."

## Demo Step 1 - Start In The App

Slide: `Let's Start With The Demo`, then switch to the browser.

SAY:

"This is the live demo app. It is a Cloudscape front end connected to an AgentCore copilot. I will ask one natural-language question, and the copilot will run the workflow through tools."

"For the live walkthrough, I am using 500 paths so the run finishes in a stage-safe window. We will generate the baseline and augmented result live in the app, then I will point to the committed 5,000-path artifact as the higher-path reference run."

DO:

Wait 3 to 5 seconds after the browser page loads before sending the first prompt. This avoids racing the app's initial conversation read.

Paste this exact prompt into the chat:

```text
Run a stage-safe headline demo at as_of_date=2022-09-30, lookback_days=1260, horizon=252, n_paths=500, w_stress=0.5305. Use the full workflow and emit tool-trace markers before and after each tool call so the Tool trace panel shows the sequence: load_data, then call plot with spec=regime_ribbon using the returned regimes_uri and threshold=0.7; run_baseline_mc with n_components=5 and seed=0 and poll until ready; run_chronos2 and poll until ready; blend_paths; price_book on the baseline paths and blended paths; then call plot with spec=pfe_overlay using the two metrics_uri values. In the final answer, report the final-date baseline and augmented EE, PFE 97.5%, and ES 97.5%; the absolute PFE delta; and the percent PFE delta only if the baseline is non-zero. End with a fenced json block named exposure_summary using raw numeric dollar values, with baseline and augmented objects containing date, ee, pfe_975, and es_975. Include both returned image_uri values: one for the regime ribbon and one for the PFE overlay, with markdown image links.
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

Plain-English explanation:

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

Use this as the live demo headline. The 5,000-path artifact is the higher-path reference run.

If the live chart is flat or visually subtle:

"The live run proves the orchestration path end to end and gives us an app-generated delta. For the higher-path reference run, I will point to the committed 5,000-path artifact in the repo."

Do not overclaim:

"This is a PoC sample book, not a production risk number."

## Demo Step 4 - Natural-Language What-If

For the staged demo, use the chat rather than the What-if panel. The panel stays in the app as a playground for follow-up exploration, but the live presentation should show the agent translating a business-language stress into tool calls.

DO:

Paste this exact prompt into the chat:

```text
What happens to exposure if EUR rates fall 50 basis points over the first 30 business days? Use the same stage-safe setup as before: as_of_date=2022-09-30, lookback_days=1260, horizon=252, n_paths=500. Translate the 50 bp move as conditioning shifts of -0.50 on EUR_2Y, EUR_5Y, and EUR_10Y, with n_anchor_days=30. Emit tool-trace markers before and after each tool call so the Tool trace panel shows the sequence. Run the sequence visibly: load_data, run_baseline_mc with n_components=5 and seed=0 and poll until ready, run_chronos2 with that conditioning and poll until ready, blend_paths with w_stress=1 for the conditional stress view, price_book on the baseline and conditional blended paths, then plot spec=pfe_overlay using the two metrics_uri values. Report final-date EE, PFE 97.5%, and ES 97.5% for baseline versus conditional augmented, and include the returned image_uri with a markdown image link.
```

SAY:

"This is the conversational part of the demo. I am not filling out a hidden form or hard-coding the workflow. I am asking a scenario question, and the agent has to sequence the tools: data, baseline, conditional Chronos-2, blend, price, and plot."

While it runs:

"A 50 basis point EUR-rates move is easier for this audience to reason about than an arbitrary FX level shift. It touches the rates block directly, it maps cleanly to the EUR two-, five-, and ten-year series, and it makes the conditional scenario feel like a real risk-manager question."

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

## After The Demo - Explain What They Saw

Return to the slides.

Slide: `The Plain-English Story`.

SAY:

"The app just demonstrated a second-lens workflow. The existing Monte Carlo is still there. Chronos-2 adds another scenario view. The blend step combines the two. The same pricing and exposure code then calculates the result."

Slide: `What The App Is Doing`.

SAY:

"The workflow is market data, baseline Monte Carlo, Chronos-2, blending, pricing, and plot. That is the whole story. The AI agent is orchestrating real tools; it is not inventing exposure numbers."

Slide: `Why This Matters`.

SAY:

"For the quant audience, the important point is that the baseline and the downstream pricing are preserved. For partner leaders, the important point is that this is a concrete AWS plus Numerix pattern: AI-assisted scenario exploration on top of an existing risk workflow."

Slide: `The Key Idea`.

SAY:

"I would describe Chronos-2 as a stress-aware second lens. It can incorporate signals like VIX, MOVE, and WTI that are difficult to add to a traditional factor model without rework."

Slide: `Recorded Headline Calibration`.

SAY:

"The recorded calibration showed baseline PFE at about 5.61 million and augmented PFE at about 6.63 million, a lift of 18.3 percent. The honest caveat is important: that is a live endpoint measurement on one PoC sample book, not a production model approval."

Slide: `Live Architecture In One Slide`.

SAY:

"The demo is deployed live on AWS. The browser streams through CloudFront and WAF to an AgentCore runtime. The agent calls nine tools. The heavy scenario jobs run on Fargate. Chronos-2 is behind a SageMaker/AutoGluon endpoint."

Slide: `What This Is And Is Not`.

SAY:

"This is a working PoC and a good partner conversation starter. It is not a production risk engine, not a regulatory claim, and not a replacement for Numerix."

Slide: `Partner Takeaway`.

SAY:

"The partner takeaway is straightforward: keep the trusted risk platform, add a foundation-model scenario lens, make exploration conversational, and validate the lift through backtesting and governance."

## Quant Expert Q&A

Q: Is Chronos-2 replacing Monte Carlo?

A: No. The baseline Monte Carlo still runs. Chronos-2 runs beside it, and the system blends the path sets.

Q: Does Chronos-2 emit joint paths?

A: No. It emits per-series quantile curves. The client reconstructs joint paths using inverse-CDF sampling and a lookback Gaussian copula.

Q: What is `w_stress`?

A: It is a deterministic stress weight between 0 and 1. Higher means the blend leans more toward the Chronos-2 stress-aware paths.

Q: Is the +18.3% number production validated?

A: No. It is a real live-endpoint calibration on one PoC sample book and one stress window. Multi-window backtesting is the next validation step.

Q: Is the copula limitation known?

A: Yes. The current PoC uses a transparent lookback Gaussian copula for joint reconstruction. Richer dependence structures would be part of future validation.

Q: Why use Fargate instead of Lambda for the heavy jobs?

A: The baseline and Chronos-2 jobs are longer-running containerized workloads, and the Chronos-2 path includes AutoGluon dependencies that are too heavy for a simple Lambda layer.

## Partner / Alliance Q&A

Q: What is the business value?

A: It shows how AWS can add AI-assisted scenario exploration to an existing risk workflow without forcing a platform replacement.

Q: Why is this relevant to Numerix?

A: Numerix owns trusted pricing and risk workflows. This PoC shows how Chronos-2 can augment scenario generation and interactive what-if exploration around that workflow.

Q: What should happen next?

A: Backtest across many dates and stress windows, broaden the book, harden governance, and define a partner-ready joint demo or offer.

Q: How should we position this externally?

A: As a PoC for stress-aware scenario augmentation, not as a production risk engine.

## Words To Use

Use:

- "Augment"
- "Second scenario lens"
- "Stress-aware view"
- "Same downstream pricing code"
- "Directional PoC result"
- "Validation and governance are next"

Avoid:

- "Replace"
- "Production risk number"
- "Regulatory approval"
- "Chronos-2 outputs joint paths"
- "Guaranteed lift"
- "Model is validated"

## Final Close

SAY:

"The one-line summary is this: Chronos-2 gives us a stress-aware scenario lens beside the existing Monte Carlo workflow. The value is not replacing the risk engine. The value is showing where a different view of the future may change tail exposure, then validating that carefully."
