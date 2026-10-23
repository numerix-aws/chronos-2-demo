# Chronos-2 / Numerix PoC — Application & Augmentation Flow

## Diagram 1 — The "correct + reweight" augmentation flow

The core quant story: parametric MC and Chronos-2 each produce a full PathSet, a
deterministic regime detector emits `w_stress`, and the blender importance-weights
the two path sets so the *same* downstream pricing/exposure code consumes the result.

```mermaid
flowchart TD
    MKT["Market data panel<br/>(21 series: rates / FX / equity / credit)"]
    COV["Exogenous covariates<br/>(VIX, MOVE, WTI)"]

    MKT --> ENGINES
    COV --> ENGINES

    subgraph ENGINES["Dual path generation"]
        direction TB
        subgraph EA["Engine A — Parametric baseline MC"]
            direction TB
            EA_DESC["PCA factors + AR(1) dynamics<br/>joint via static loadings<br/>(NO covariates)"]
            PARAM_PS["Parametric PathSet<br/>(N x H x 21)"]
            EA_DESC --> PARAM_PS
        end
        subgraph EB["Engine B — Chronos-2 foundation model"]
            direction TB
            EB_DESC["AutoGluon endpoint to per-series quantiles<br/>(ingests VIX / MOVE / WTI)"]
            EB_RECON["inverse-CDF + lookback Gaussian copula"]
            CHRONOS_PS["Chronos-2 PathSet<br/>(N x H x 21)"]
            EB_DESC --> EB_RECON --> CHRONOS_PS
        end
    end

    COV -. "fed only to Engine B" .-> EB

    REGIME["Regime detector (deterministic)<br/>3 features: rolling vol, FX-rates corr, vol-of-vol<br/>percentile-ranked"]
    WSTRESS["w_stress in [0,1]"]
    REGIME --> WSTRESS

    BLEND["Blender (importance weighting)<br/>tail (top/bottom 5%): parametric (1 - w_stress) / Chronos-2 w_stress<br/>body: 0.9 / 0.1<br/>every path non-zero"]
    BLENDED["Blended weighted PathSet"]

    PARAM_PS --> BLEND
    CHRONOS_PS --> BLEND
    WSTRESS --> BLEND
    BLEND --> BLENDED

    PRICING["Shared closed-form pricing / exposure engine<br/>XCCY swaps + equity fwd + CDS<br/>(same code for parametric / Chronos-2 / blended)"]
    METRICS["Exposure metrics: EE, PFE(97.5%), ES<br/>(weighted percentiles)"]

    BLENDED --> PRICING --> METRICS

    NOTE["Deliberate value asymmetry:<br/>the parametric baseline does NOT see VIX/MOVE/WTI;<br/>Chronos-2 does. This gap IS the story, not a bug."]

    classDef augLayer fill:#fde68a,stroke:#b45309,stroke-width:2px,color:#1f2937;
    classDef noteBox fill:#e0f2fe,stroke:#0369a1,stroke-width:1px,color:#0c4a6e,font-style:italic;
    class REGIME,WSTRESS,BLEND,BLENDED augLayer;
    class NOTE noteBox;
```

## Diagram 2 — Agentic tool orchestration

How the AgentCore copilot sequences the 9 MCP tools for a what-if query. The two
heavy engines (`run_baseline_mc`, `run_chronos2`) follow an async launch-on-Fargate +
poll pattern; results stream back to the analyst over SSE.

```mermaid
flowchart TD
    ANALYST["Quant analyst<br/>'PFE if EUR rates fall 50bps?'"]
    RUNTIME["AgentCore Runtime<br/>(Strands agent, Claude Sonnet 4.6)"]
    GATEWAY["AgentCore Gateway<br/>(MCP, 9 tools)"]

    ANALYST -->|NL question| RUNTIME
    RUNTIME <--> GATEWAY

    subgraph TOOLS["9 MCP tools"]
        direction TB
        T1["1 - load_data"]
        T2["2 - run_baseline_mc<br/>(async Fargate)"]
        T2C["3 - check_baseline_mc<br/>(poll)"]
        T3["4 - run_chronos2<br/>(async Fargate, conditioning: series shifts)"]
        T3C["5 - check_chronos2<br/>(poll)"]
        T4["6 - blend_paths"]
        T5["7 - price_book"]
        T6["8 - plot"]
        T7["lookup_use_case<br/>(ad-hoc / side tool)"]

        T1 --> T2
        T2 <--> T2C
        T2C --> T3
        T3 <--> T3C
        T3C --> T4
        T4 --> T5
        T5 --> T6
    end

    GATEWAY --> TOOLS
    GATEWAY -. ad-hoc .-> T7

    SAGEMAKER["SageMaker Chronos-2 endpoint"]
    T3 -->|Fargate task invokes| SAGEMAKER

    RESULTS["Results stream back (SSE)"]
    T6 --> RESULTS
    RESULTS --> ANALYST

    classDef asyncFargate fill:#fca5a5,stroke:#b91c1c,stroke-width:2px,color:#1f2937;
    class T2,T3 asyncFargate;
```
