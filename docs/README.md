# Documentation index

Start with the [top-level README](../README.md). It covers the problem, the
approach, the measured results, and the engineering overview. Everything below
is supporting depth.

## Results (committed evidence)

| File | What it records |
|---|---|
| [`results/headline_calibration_5000paths.json`](results/headline_calibration_5000paths.json) | **Headline run.** Live endpoint, 5,000 paths per engine, as-of 2022-09-30: PFE 97.5% $5.61M → $6.63M (+18.3%) |
| [`results/headline_calibration.json`](results/headline_calibration.json) | 500-path stage-safe run with the full run spec, provenance (data hashes, image digests), attribution, and coverage diagnostics |
| [`results/live_reproducibility.json`](results/live_reproducibility.json) | Three independent live runs of the 500-path spec, identical to the cent (per-run event logs alongside) |
| [`results/latency_benchmark.json`](results/latency_benchmark.json) | Closed-form exposure vs nested Monte Carlo: 0.28s vs 550s (≈2,000×) |

## Demo materials

| File | Audience |
|---|---|
| [`demo/slides.md`](demo/slides.md) ([PDF](demo/slides.pdf)) | Quant-audience deck (Marp) |
| [`demo/demo-script.md`](demo/demo-script.md) | Presenter script with talk track, caveats, and anticipated Q&A |
| [`demo/app-flow.md`](demo/app-flow.md) | Mermaid diagrams: the augmentation flow and the agent's tool orchestration |
| [`demo/infra-architecture.png`](demo/infra-architecture.png) | AWS deployment architecture (editable [`.drawio`](demo/infra-architecture.drawio)) |

## Operating the stack

- [`runbook.md`](runbook.md): deploy, demo, and teardown for the full AWS stack
  (CDK, AgentCore, endpoint, SPA).

## Design history

`superpowers/specs/` holds the design specs and `superpowers/plans/` holds the
task-by-task implementation plans. These are the working record of how the PoC
was built. Where a spec and the shipped code disagree, the code is authoritative.

- [PoC design spec](superpowers/specs/2026-05-22-numerix-chronos2-poc-design.md): the original design, with dated banners for later re-architecture
- [Reproducible quant execution](superpowers/specs/2026-07-21-reproducible-quant-execution-design.md): hashed run specs and provenance
- [Tool trace panel v2](superpowers/specs/2026-08-07-tool-trace-panel-v2-design.md): UI for the agent's tool trace
- Multi-agent experiments: [hierarchical](superpowers/specs/2026-08-13-hierarchical-delegation-experiment-design.md) · [ReAct](superpowers/specs/2026-08-13-react-orchestration-experiment-design.md) · [reflexion](superpowers/specs/2026-08-13-reflexion-critic-experiment-design.md)

## Use-case briefs

[`../agent/knowledge/`](../agent/knowledge/) has short briefs on where the same
augmentation pattern applies beyond PFE: FRTB IMA ES, IM/VM forecasting,
stress-test design, scenario limits, market-data gap filling, long-context
conditioning, and temporal hierarchies. The copilot also uses them as its
knowledge base.
