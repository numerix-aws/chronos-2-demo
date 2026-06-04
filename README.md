# Chronos-2 × Numerix PoC — Quant Pipeline

End-to-end pipeline demonstrating Chronos-2 used as an **augmentation function**
on top of a parametric Monte Carlo engine, scored against a sample
cross-currency swap book by EE / PFE@97.5 / ES@97.5.

The headline demo notebook is `notebooks/headline_demo.ipynb`. Plan B (UX)
sits on top of these same Python modules via an AgentCore copilot.

See `docs/superpowers/specs/2026-05-22-numerix-chronos2-poc-design.md` for the
PoC design and `docs/superpowers/plans/2026-05-22-plan-a-quant-pipeline*.md`
for the implementation plan series.

---

## Quick start

### Prerequisites

- Python 3.11+
- AWS credentials with permission to invoke a SageMaker endpoint in `us-east-1`
- A FRED API key (free; https://fred.stlouisfed.org/docs/api/api_key.html)

### Setup

```bash
git clone <this repo>
cd chronos-2-demo
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### Snapshot the data

One-shot pull of the FX, rates, and covariate panels into `data/curated/`:

```bash
python scripts/snapshot_data.py --fred-api-key $FRED_API_KEY
```

This produces `data/curated/panel.parquet` and `data/curated/covariates.parquet`.

### Deploy the Chronos-2 endpoint (AutoGluon Cloud)

Deploys the real `amazon/chronos-2` model via AutoGluon Cloud. Requires the
`deploy` extra (`pip install -e ".[deploy]"`). Serverless is the default —
it scales to zero between demos — and needs an S3 cache for the model artifact:

```bash
python scripts/deploy_chronos2_endpoint.py --action deploy \
  --cache-uri s3://YOUR-BUCKET/fm-cache
```

The endpoint returns per-series quantiles; the client reconstructs joint paths.
For lowest latency you can deploy a GPU real-time endpoint instead
(`--mode realtime --instance-type ml.g5.xlarge`).

When done with the demo:

```bash
python scripts/deploy_chronos2_endpoint.py --action teardown --endpoint-name chronos2-demo-ep
```

### Run the headline notebook

```bash
jupyter lab notebooks/headline_demo.ipynb
```

Run the cells top-to-bottom. The money-shot chart is the PFE overlay in Beat 7.

---

## Repository layout

```
src/chronos2_demo/
  config.py                 # paths + demo constants
  types.py                  # PathSet (the shared scenario container)
  data/                     # FRED/ECB fetchers, panel alignment, regime labels
  models/                   # baseline parametric MC + Chronos-2 client
  augmentation/             # regime detector + blender (the augmentation core)
  pricing/                  # XCCY book, swap valuation, EE/PFE/ES
  diagnostics/              # coverage, tail dependence, distribution distance
  plotting/                 # PFE overlay, path fans, regime ribbon
  infra/                    # Chronos-2 deploy/teardown via AutoGluon Cloud
notebooks/headline_demo.ipynb
scripts/snapshot_data.py
scripts/deploy_chronos2_endpoint.py
tests/                      # full test suite

# Plan B (UX + agent) — wraps the Plan A package
agent/                      # AgentCore copilot: 9 tool schemas, system prompt, Strands runtime, knowledge briefs
tools/                      # tool implementations: lambda/ handlers + fargate/ (baseline_mc, run_chronos2) workers
infra/                      # CDK app: 7 stacks (network, storage, tools, agent, api, frontend, observability)
frontend/                   # Cloudscape React SPA (chat + what-if panel, SSE streaming)
docs/runbook.md             # deploy / demo / teardown runbook
```

## Running the test suite

```bash
pytest -q
```

The test suite is hermetic (no network, no SageMaker calls) — Chronos-2
endpoint calls and FRED/ECB fetchers are mocked.

To regenerate the headline regression fixture (rare):

```bash
python tests/fixtures/build_headline_panel.py
```

## Architecture in one paragraph

The parametric engine and Chronos-2 produce two `PathSet`s over the same series,
horizon, and dates. A deterministic regime detector emits `w_stress ∈ [0, 1]`
at the as-of date from rolling features (vol, vol-of-vol, |rates–FX corr|).
The blender stacks the two path sets and reweights them: in the body each
path keeps a (1 − body_chronos_share) / body_chronos_share split, in the tail
buckets it keeps a (1 − w_stress) / w_stress split. Pricing then runs the same
EE / PFE / ES code path on the blended set as on the baseline set. *Same engine,
different inputs* — that is the demo's central claim.

## Design decisions worth knowing

- **PathSet is the contract.** Every model emits one; every consumer reads one.
  Locked in `src/chronos2_demo/types.py` before any engine was implemented.
- **Augmentation is importance reweighting, not path replacement.** The blender
  never deletes a parametric path; it just sometimes weighs Chronos-2 paths more.
- **Pricing uses a closed-form XCCY MtM proxy.** Not a full curve build —
  out of scope for the PoC. Locked formula in `pricing/xccy.py`.
- **The notebook is the executable spec.** If `tests/test_notebook_smoke.py`
  passes, the notebook will run end-to-end against real data once the
  SageMaker endpoint is up.
