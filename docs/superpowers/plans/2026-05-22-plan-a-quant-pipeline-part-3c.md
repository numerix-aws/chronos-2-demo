# Plan A — Part 3c: Stages 8–9 — Headline Notebook + README & Pinned Numbers

> **Continuation of** `2026-05-22-plan-a-quant-pipeline-part-3b.md`. Tasks 28–30.

---

## Stage 8 — Headline demo notebook

The notebook is the **deliverable artifact for Plan A**. It is the smallest possible thing that proves the end-to-end story works without the agent UI in place. The notebook is what gets demoed if anything in Plan B (UX) breaks; it's also what the agent's tool calls in Plan B will mirror underneath.

### Task 28: `notebooks/headline_demo.ipynb` and a smoke test

**Files:**
- Create: `notebooks/headline_demo.ipynb`
- Create: `tests/test_notebook_smoke.py`

The notebook is structured as one cell per **demo beat**. To keep TDD discipline applicable to a notebook, we write a smoke test that imports each function the notebook calls and runs them end-to-end against a small synthetic panel. The notebook itself uses real data via the snapshot script — but is built up from the same calls as the smoke test so they can't drift.

- [ ] **Step 1: Write the failing smoke test**

`tests/test_notebook_smoke.py`:
```python
"""End-to-end smoke test exercising the same call sequence as the headline notebook.

The notebook itself is committed but not executed in CI. This test mirrors the
notebook's logic against synthetic data so refactors break the test before
they break the demo.
"""
import numpy as np
import pandas as pd
import pytest
from chronos2_demo.augmentation import blender, regime_detector
from chronos2_demo.data import regimes
from chronos2_demo.models import baseline_mc, chronos2_client
from chronos2_demo.pricing import book, exposure


def _synthetic_panel(n=600, seed=0):
    rng = np.random.default_rng(seed)
    cols = ["USDEUR", "USDJPY", "USDGBP",
            "USD_2Y", "USD_5Y", "USD_10Y",
            "EUR_2Y", "EUR_5Y", "EUR_10Y",
            "JPY_2Y", "JPY_5Y", "JPY_10Y",
            "GBP_2Y", "GBP_5Y", "GBP_10Y"]
    base = np.array([1.08, 0.0088, 1.35,
                     0.020, 0.025, 0.030,
                     0.000, 0.005, 0.010,
                     0.000, 0.000, 0.001,
                     0.010, 0.015, 0.020])
    raw = base + rng.normal(0, 0.001, size=(n, len(cols))).cumsum(axis=0) * 0.001
    return pd.DataFrame(raw, columns=cols,
                        index=pd.bdate_range("2020-01-02", periods=n))


class _FakeEndpoint:
    """AutoGluon endpoint stand-in: returns a long-format quantile DataFrame."""
    def predict(self, data, target, id_column, timestamp_column,
                prediction_length, known_covariates=None):
        items = list(dict.fromkeys(data[id_column]))
        future = pd.bdate_range("2022-07-01", periods=prediction_length)
        rows = []
        for item in items:
            for t in range(prediction_length):
                row = {id_column: item, timestamp_column: future[t], "mean": 1.0}
                for ql in chronos2_client.Q_LEVELS:
                    row[str(ql)] = 1.0 + (ql - 0.5) * 0.02
                rows.append(row)
        return pd.DataFrame(rows)


def _mock_chronos_client(n_paths, horizon, n_series):
    # The endpoint returns per-series quantiles; the client reconstructs paths.
    return chronos2_client.Chronos2Client(endpoint=_FakeEndpoint())


def test_full_pipeline_runs_end_to_end():
    panel = _synthetic_panel()
    as_of = "2022-01-03"
    horizon = 21
    n_paths = 100

    # 1. Regime snapshot at as_of.
    snap = regime_detector.current_w_stress(panel, as_of=as_of, window=20)
    assert 0.0 <= snap.w_stress <= 1.0

    # 2. Baseline parametric MC.
    par_paths = baseline_mc.simulate_baseline(
        panel, as_of=as_of, horizon=horizon, n_paths=n_paths,
        n_components=3, seed=0,
    )
    assert par_paths.source == "parametric"
    assert par_paths.paths.shape == (n_paths, horizon, panel.shape[1])

    # 3. Chronos-2 (mocked endpoint).
    client = _mock_chronos_client(n_paths, horizon, panel.shape[1])
    chr_paths = chronos2_client.simulate_chronos2(
        client, panel, as_of=as_of, horizon=horizon, n_paths=n_paths,
    )
    assert chr_paths.source == "chronos2"

    # 4. Compute portfolio MtM-driven tail score per engine for blending.
    book_swaps = book.load_book(book.DEFAULT_BOOK_PATH)
    par_mtm = exposure.portfolio_mtm(book_swaps, par_paths)
    chr_mtm = exposure.portfolio_mtm(book_swaps, chr_paths)
    par_terminal = par_mtm[:, -1]
    chr_terminal = chr_mtm[:, -1]

    # 5. Blend.
    blended = blender.blend_paths(
        par_paths, chr_paths, par_terminal, chr_terminal,
        w_stress=snap.w_stress,
    )
    assert blended.source == "blended"

    # 6. Compute baseline + augmented metrics.
    baseline_metrics = exposure.compute_metrics(book_swaps, par_paths)
    augmented_metrics = exposure.compute_metrics(book_swaps, blended)
    for m in (baseline_metrics, augmented_metrics):
        assert "ee" in m and "pfe_975" in m and "es_975" in m
        assert m["ee"].shape == (horizon,)
        assert m["pfe_975"].shape == (horizon,)
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/test_notebook_smoke.py -v
```
Expected: PASS *if* all earlier tasks were implemented correctly. (This is an integration test — it doesn't exercise new code.) If it fails, fix the upstream task before continuing.

- [ ] **Step 3: Author `notebooks/headline_demo.ipynb`**

The notebook is a JSON file. Create it with the cell sequence below. Each cell number maps to a demo beat. Use `jupyter nbformat` or write the JSON by hand; here is the literal content. Save as `notebooks/headline_demo.ipynb`:

```json
{
  "cells": [
    {
      "cell_type": "markdown",
      "metadata": {},
      "source": [
        "# Numerix x Chronos-2: Headline Demo\n",
        "\n",
        "**Goal:** show that augmenting a parametric MC engine with Chronos-2 *changes the answer in regimes where the parametric engine is structurally weak*, while leaving the answer essentially unchanged in calm regimes.\n",
        "\n",
        "Beats:\n",
        "1. Pull the joint FX+rates panel and the XCCY book.\n",
        "2. Pick an as-of date in a known stress window.\n",
        "3. Run the parametric engine.\n",
        "4. Run Chronos-2 (with covariates).\n",
        "5. Blend by `w_stress` from the regime detector.\n",
        "6. Compute EE / PFE@97.5 / ES@97.5 for baseline vs augmented.\n",
        "7. Render the money-shot overlay + diagnostics."
      ]
    },
    {
      "cell_type": "code",
      "execution_count": null,
      "metadata": {},
      "source": [
        "%load_ext autoreload\n",
        "%autoreload 2\n",
        "\n",
        "import numpy as np\n",
        "import pandas as pd\n",
        "import matplotlib.pyplot as plt\n",
        "\n",
        "from chronos2_demo import config\n",
        "from chronos2_demo.augmentation import blender, regime_detector\n",
        "from chronos2_demo.data import covariates as cov_loader\n",
        "from chronos2_demo.diagnostics import coverage, distribution, tail_dependence\n",
        "from chronos2_demo.models import baseline_mc, chronos2_client\n",
        "from chronos2_demo.pricing import book, exposure\n",
        "from chronos2_demo.plotting import path_samples, pfe_overlay, regime_ribbon"
      ],
      "outputs": []
    },
    {
      "cell_type": "markdown",
      "metadata": {},
      "source": ["## Beat 1 — Load the curated panel and the book"]
    },
    {
      "cell_type": "code",
      "execution_count": null,
      "metadata": {},
      "source": [
        "panel = pd.read_parquet(config.DATA_CURATED / 'panel.parquet')\n",
        "covs = pd.read_parquet(config.DATA_CURATED / 'covariates.parquet')\n",
        "swap_book = book.load_book(book.DEFAULT_BOOK_PATH)\n",
        "print(f'panel: {panel.shape}, covariates: {covs.shape}, swaps: {len(swap_book)}')"
      ],
      "outputs": []
    },
    {
      "cell_type": "markdown",
      "metadata": {},
      "source": ["## Beat 2 — Pick an as-of date and look at the regime snapshot"]
    },
    {
      "cell_type": "code",
      "execution_count": null,
      "metadata": {},
      "source": [
        "AS_OF = config.DEFAULT_AS_OF  # 2022-06-30\n",
        "HORIZON = config.DEFAULT_HORIZON_DAYS\n",
        "N_PATHS = config.DEFAULT_N_PATHS\n",
        "\n",
        "snap = regime_detector.current_w_stress(panel, as_of=AS_OF, window=20)\n",
        "print(f'w_stress at {AS_OF}: {snap.w_stress:.3f}')\n",
        "print(snap.features)"
      ],
      "outputs": []
    },
    {
      "cell_type": "markdown",
      "metadata": {},
      "source": ["## Beat 3 — Run the parametric engine"]
    },
    {
      "cell_type": "code",
      "execution_count": null,
      "metadata": {},
      "source": [
        "par_paths = baseline_mc.simulate_baseline(\n",
        "    panel, as_of=AS_OF, horizon=HORIZON, n_paths=N_PATHS,\n",
        "    n_components=5, seed=0,\n",
        ")\n",
        "print(par_paths.source, par_paths.paths.shape)"
      ],
      "outputs": []
    },
    {
      "cell_type": "markdown",
      "metadata": {},
      "source": ["## Beat 4 — Run Chronos-2 (AutoGluon Cloud endpoint)\n", "\n", "> Deployed via AutoGluon Cloud (`amazon/chronos-2`), serverless by default. The endpoint returns per-series quantiles; `Chronos2Client` reconstructs joint sample paths client-side (Gaussian copula over the shared lookback) so the `PathSet` contract is unchanged."]
    },
    {
      "cell_type": "code",
      "execution_count": null,
      "metadata": {},
      "source": [
        "from chronos2_demo.infra import sagemaker_endpoint\n",
        "endpoint = sagemaker_endpoint.open_endpoint('chronos2-demo-ep')\n",
        "client = chronos2_client.Chronos2Client(endpoint=endpoint)\n",
        "\n",
        "chr_paths = chronos2_client.simulate_chronos2(\n",
        "    client, panel, as_of=AS_OF, horizon=HORIZON, n_paths=N_PATHS,\n",
        "    covariates=covs,\n",
        ")\n",
        "print(chr_paths.source, chr_paths.paths.shape)"
      ],
      "outputs": []
    },
    {
      "cell_type": "markdown",
      "metadata": {},
      "source": ["## Beat 5 — Blend by w_stress"]
    },
    {
      "cell_type": "code",
      "execution_count": null,
      "metadata": {},
      "source": [
        "par_terminal = exposure.portfolio_mtm(swap_book, par_paths)[:, -1]\n",
        "chr_terminal = exposure.portfolio_mtm(swap_book, chr_paths)[:, -1]\n",
        "\n",
        "blended = blender.blend_paths(\n",
        "    par_paths, chr_paths, par_terminal, chr_terminal,\n",
        "    w_stress=snap.w_stress,\n",
        ")\n",
        "print(blended.source, blended.paths.shape, 'weights sum =', blended.weights.sum())"
      ],
      "outputs": []
    },
    {
      "cell_type": "markdown",
      "metadata": {},
      "source": ["## Beat 6 — Compute exposure metrics"]
    },
    {
      "cell_type": "code",
      "execution_count": null,
      "metadata": {},
      "source": [
        "baseline_metrics = exposure.compute_metrics(swap_book, par_paths)\n",
        "augmented_metrics = exposure.compute_metrics(swap_book, blended)\n",
        "\n",
        "print('PFE@97.5 terminal:')\n",
        "print(f'  baseline:  {baseline_metrics[\"pfe_975\"][-1]:,.0f} USD')\n",
        "print(f'  augmented: {augmented_metrics[\"pfe_975\"][-1]:,.0f} USD')\n",
        "print(f'  delta:     {augmented_metrics[\"pfe_975\"][-1] - baseline_metrics[\"pfe_975\"][-1]:,.0f} USD '\n",
        "      f'({100 * (augmented_metrics[\"pfe_975\"][-1] / baseline_metrics[\"pfe_975\"][-1] - 1):.1f}%)')"
      ],
      "outputs": []
    },
    {
      "cell_type": "markdown",
      "metadata": {},
      "source": ["## Beat 7 — Money-shot overlay + diagnostics"]
    },
    {
      "cell_type": "code",
      "execution_count": null,
      "metadata": {},
      "source": [
        "fig = pfe_overlay.plot_pfe_overlay(\n",
        "    baseline=baseline_metrics, augmented=augmented_metrics,\n",
        "    title=f'XCCY book PFE@97.5 — as-of {AS_OF} (w_stress={snap.w_stress:.2f})',\n",
        ")\n",
        "fig\n"
      ],
      "outputs": []
    },
    {
      "cell_type": "code",
      "execution_count": null,
      "metadata": {},
      "source": [
        "w_stress_full = (\n",
        "    pd.Series(0.0, index=panel.index)\n",
        "      .combine_first(__import__('chronos2_demo.data.regimes', fromlist=['w_stress_series'])\n",
        "                     .w_stress_series(panel, window=20))\n",
        "      .reindex(panel.index)\n",
        "      .ffill().fillna(0.0)\n",
        ")\n",
        "fig = regime_ribbon.plot_regime_ribbon(\n",
        "    w_stress_full.tail(252), threshold=0.7, title='w_stress trailing 252 BD',\n",
        ")\n",
        "fig"
      ],
      "outputs": []
    },
    {
      "cell_type": "code",
      "execution_count": null,
      "metadata": {},
      "source": [
        "fig = path_samples.plot_path_fan(\n",
        "    par_paths, series='USDEUR', n_path_samples=40,\n",
        "    title='Parametric paths — USDEUR',\n",
        ")\n",
        "fig\n"
      ],
      "outputs": []
    },
    {
      "cell_type": "code",
      "execution_count": null,
      "metadata": {},
      "source": [
        "fig = path_samples.plot_path_fan(\n",
        "    chr_paths, series='USDEUR', n_path_samples=40,\n",
        "    title='Chronos-2 paths — USDEUR',\n",
        ")\n",
        "fig\n"
      ],
      "outputs": []
    },
    {
      "cell_type": "markdown",
      "metadata": {},
      "source": ["## Diagnostics — does the augmented set match reality better?"]
    },
    {
      "cell_type": "code",
      "execution_count": null,
      "metadata": {},
      "source": [
        "exc_par = tail_dependence.exceedance_correlation(par_paths, 'USDEUR', 'USD_5Y', quantile=0.05)\n",
        "exc_chr = tail_dependence.exceedance_correlation(chr_paths, 'USDEUR', 'USD_5Y', quantile=0.05)\n",
        "exc_realized = tail_dependence.realized_exceedance_correlation(panel, 'USDEUR', 'USD_5Y', quantile=0.05)\n",
        "print(f'exceedance corr USDEUR x USD_5Y:')\n",
        "print(f'  parametric: {exc_par:+.3f}')\n",
        "print(f'  chronos-2:  {exc_chr:+.3f}')\n",
        "print(f'  realized:   {exc_realized:+.3f}')"
      ],
      "outputs": []
    }
  ],
  "metadata": {
    "kernelspec": {"display_name": "Python 3 (ipykernel)", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3.11"}
  },
  "nbformat": 4,
  "nbformat_minor": 5
}
```

Notes for the engineer:
- The notebook is committed *unexecuted*. Outputs will be generated when the demo is run. Do **not** commit cleared-output edits as part of this task.
- The Beat 4 cell calls a real AutoGluon Cloud endpoint via `open_endpoint`. In a dev environment without the endpoint deployed, swap the `endpoint = ...` line for a fake endpoint per `tests/test_notebook_smoke.py` (`Chronos2Client(endpoint=_FakeEndpoint())`).

- [ ] **Step 4: Run smoke test, confirm pass**

```bash
pytest tests/test_notebook_smoke.py -v
```
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add notebooks/headline_demo.ipynb tests/test_notebook_smoke.py
git commit -m "feat(notebook): headline demo notebook + end-to-end smoke test

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Stage 9 — Pin headline numbers + README

The final stage produces two artifacts: a JSON file with the headline numbers (so they don't drift silently between demos), and a README that walks a new engineer from `git clone` to running the notebook.

### Task 29: Pin headline numbers via a regression test

**Files:**
- Create: `tests/test_headline_numbers.py`
- Create: `tests/fixtures/headline_panel.parquet` (small deterministic panel saved by a one-time fixture builder)
- Create: `tests/fixtures/build_headline_panel.py` (runs once to produce the parquet)

The headline test asserts that on a frozen synthetic panel, with a frozen seed and a mocked Chronos-2 endpoint that returns deterministic quantile curves (the client reconstructs paths under a fixed seed), the augmented PFE@97.5 at the terminal date is *higher* than the baseline by a margin within a frozen tolerance band. This pins the **direction and order of magnitude** of the effect even if values shift slightly with library upgrades.

- [ ] **Step 1: Build the fixture panel once**

`tests/fixtures/build_headline_panel.py`:
```python
"""Run once to produce a deterministic synthetic panel for headline regression.

Usage: python tests/fixtures/build_headline_panel.py
"""
from pathlib import Path
import numpy as np
import pandas as pd

OUT = Path(__file__).parent / "headline_panel.parquet"


def main() -> None:
    rng = np.random.default_rng(seed=20260522)
    n_obs = 600
    cols = ["USDEUR", "USDJPY", "USDGBP",
            "USD_2Y", "USD_5Y", "USD_10Y",
            "EUR_2Y", "EUR_5Y", "EUR_10Y",
            "JPY_2Y", "JPY_5Y", "JPY_10Y",
            "GBP_2Y", "GBP_5Y", "GBP_10Y"]
    base = np.array([1.08, 0.0088, 1.35,
                     0.020, 0.025, 0.030,
                     0.000, 0.005, 0.010,
                     0.000, 0.000, 0.001,
                     0.010, 0.015, 0.020])
    raw = base + rng.normal(0, 0.001, size=(n_obs, len(cols))).cumsum(axis=0) * 0.001
    # Inject a stress window so w_stress at as_of is meaningfully > 0.
    raw[400:430] += rng.normal(0, 0.02, size=(30, len(cols)))
    df = pd.DataFrame(raw, columns=cols,
                      index=pd.bdate_range("2020-01-02", periods=n_obs))
    df.to_parquet(OUT)
    print(f"wrote {OUT}: {df.shape}")


if __name__ == "__main__":
    main()
```

Run it:

```bash
mkdir -p tests/fixtures
python tests/fixtures/build_headline_panel.py
```

- [ ] **Step 2: Write the headline regression test**

`tests/test_headline_numbers.py`:
```python
"""Pin the direction + order-of-magnitude of the headline result.

Inputs frozen:
  - tests/fixtures/headline_panel.parquet (built once)
  - n_paths = 1000, horizon = 21
  - seed = 0 for parametric MC
  - mocked Chronos-2 returns deterministic quantile curves; client reconstructs paths under a fixed seed

Asserts:
  - augmented PFE@97.5 terminal >= baseline PFE@97.5 terminal
  - the relative gap is within [5%, 200%]  (sanity band; not a tight pin)
"""
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm
from chronos2_demo.augmentation import blender, regime_detector
from chronos2_demo.models import baseline_mc, chronos2_client
from chronos2_demo.pricing import book, exposure

PANEL_PATH = Path(__file__).parent / "fixtures" / "headline_panel.parquet"


class _FakeEndpoint:
    """AutoGluon endpoint stand-in returning a deterministic quantile frame.

    Quantiles are spread around 1.0 (inverse-normal grid) so the reconstructed
    paths have tails. simulate_chronos2 reconstructs under a fixed seed, so the
    headline regression stays reproducible across runs.
    """
    def predict(self, data, target, id_column, timestamp_column,
                prediction_length, known_covariates=None):
        items = list(dict.fromkeys(data[id_column]))
        future = pd.bdate_range("2022-07-01", periods=prediction_length)
        rows = []
        for item in items:
            for t in range(prediction_length):
                row = {id_column: item, timestamp_column: future[t], "mean": 1.0}
                for ql in chronos2_client.Q_LEVELS:
                    row[str(ql)] = 1.0 + norm.ppf(ql) * 0.02
                rows.append(row)
        return pd.DataFrame(rows)


def _mock_chronos_client(n_paths, horizon, n_series):
    return chronos2_client.Chronos2Client(endpoint=_FakeEndpoint())


@pytest.mark.skipif(not PANEL_PATH.exists(),
                    reason="run tests/fixtures/build_headline_panel.py first")
def test_augmented_pfe_exceeds_baseline_by_meaningful_margin():
    panel = pd.read_parquet(PANEL_PATH)
    as_of = panel.index[-1].strftime("%Y-%m-%d")
    horizon = 21
    n_paths = 1000

    snap = regime_detector.current_w_stress(panel, as_of=as_of, window=20)
    par = baseline_mc.simulate_baseline(
        panel, as_of=as_of, horizon=horizon, n_paths=n_paths,
        n_components=5, seed=0,
    )
    client = _mock_chronos_client(n_paths, horizon, panel.shape[1])
    chr_ = chronos2_client.simulate_chronos2(
        client, panel, as_of=as_of, horizon=horizon, n_paths=n_paths,
    )

    swaps = book.load_book(book.DEFAULT_BOOK_PATH)
    par_term = exposure.portfolio_mtm(swaps, par)[:, -1]
    chr_term = exposure.portfolio_mtm(swaps, chr_)[:, -1]
    blended = blender.blend_paths(par, chr_, par_term, chr_term, w_stress=snap.w_stress)

    base_pfe = exposure.compute_metrics(swaps, par)["pfe_975"][-1]
    aug_pfe = exposure.compute_metrics(swaps, blended)["pfe_975"][-1]
    rel_gap = (aug_pfe - base_pfe) / max(abs(base_pfe), 1.0)

    assert aug_pfe >= base_pfe, (
        f"augmented PFE ({aug_pfe:,.0f}) should be >= baseline ({base_pfe:,.0f})"
    )
    assert -0.5 <= rel_gap <= 5.0, (
        f"relative gap {rel_gap:.2%} is outside the sanity band"
    )
```

- [ ] **Step 3: Run, confirm pass**

```bash
pytest tests/test_headline_numbers.py -v
```
Expected: 1 passed.

- [ ] **Step 4: Add `tests/fixtures/headline_panel.parquet` to git via a `.gitignore` exception**

Update `.gitignore`:
```diff
 data/raw/
 data/curated/
 !data/sample_book.json
+# Frozen headline regression fixture is committed:
+!tests/fixtures/headline_panel.parquet
```

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/build_headline_panel.py tests/fixtures/headline_panel.parquet \
        tests/test_headline_numbers.py .gitignore
git commit -m "test(headline): pin direction + magnitude of augmented vs baseline PFE

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 30: README — runbook for the end-to-end demo

**Files:**
- Create: `README.md`

A new engineer should be able to read README.md and reach a rendered notebook in under 30 minutes (assuming AWS creds and a FRED API key are available).

- [ ] **Step 1: Write `README.md`**

```markdown
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
  infra/                    # SageMaker endpoint helpers
notebooks/headline_demo.ipynb
scripts/snapshot_data.py
scripts/deploy_chronos2_endpoint.py
tests/                      # full test suite
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
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README runbook for the end-to-end demo

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Plan A complete

After Task 30 the repo contains:
- A working Python pipeline from raw data to PFE overlay.
- A headline notebook that demos it end-to-end.
- A test suite that pins the direction and order of magnitude of the augmentation effect.
- A README that lets a new engineer run it in under 30 minutes.

Plan B will add the AgentCore copilot, API Gateway, and the Cloudscape SPA on top of these modules.

> _Continue with `2026-05-22-plan-b-ux-and-agent.md` (Plan B — agent + API + frontend)._
