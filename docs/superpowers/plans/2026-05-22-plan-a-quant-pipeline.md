# Plan A — Numerix x Chronos-2 Quant Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the end-to-end quant pipeline (data → parallel scenario engines → regime-aware augmentation → XCCY pricing/PFE → diagnostics) in pure Python, drivable from a Jupyter notebook that walks the headline demo narrative.

**Architecture:** Python 3.11 package `chronos2_demo` with focused modules per responsibility (data, regime detection, baseline MC, Chronos-2 client, augmentation, pricing, plotting, diagnostics). Chronos-2 is deployed via AutoGluon Cloud (serverless default) and returns per-series quantiles, which the client reconstructs into joint paths client-side (inverse-CDF + lookback Gaussian copula); baseline MC runs in-process. A `notebooks/headline_demo.ipynb` notebook drives the full story end-to-end. (See part-2b for the authoritative Stage 3 detail.)

**Tech Stack:** Python 3.11, numpy, scipy, pandas, scikit-learn, matplotlib, boto3, autogluon-cloud (deploy-only extra), pytest, Jupyter. Data sources: FRED API (rates), ECB SDW (FX), public covariates (VIX, MOVE, WTI). Storage: local Parquet + S3.

**Reference spec:** `docs/superpowers/specs/2026-05-22-numerix-chronos2-poc-design.md`.

---

> **Before Task 1:** read the **Engineering Discipline** section in `CLAUDE.md` at the repo root. It applies repo-wide: think first, simplicity, surgical changes, verify don't trust, stop-and-ask. Plan-A-specific reinforcements (asymmetric covariates, hermetic tests, pinned headline numbers) live in `CLAUDE.md`'s "Plan-execution conventions" section.

---

## File Structure (locked in before tasks)

```
chronos-2-demo/
├── pyproject.toml                      # package config, deps, pytest
├── README.md                           # how to run the pipeline + notebook
├── .gitignore                          # data/, .venv/, __pycache__/, .ipynb_checkpoints/
├── data/                               # gitignored; raw + curated parquet
│   ├── raw/                            # downloaded snapshots
│   └── curated/                        # aligned panels, regime labels, sample book
├── src/chronos2_demo/
│   ├── __init__.py
│   ├── config.py                       # paths, constants (as_of dates, stress windows)
│   ├── data/
│   │   ├── __init__.py
│   │   ├── fetch.py                    # FRED/ECB/public fetchers
│   │   ├── align.py                    # joint resampling, ffill, train/test slicing
│   │   ├── covariates.py               # VIX/MOVE/WTI loader
│   │   └── regimes.py                  # deterministic regime labeler
│   ├── models/
│   │   ├── __init__.py
│   │   ├── baseline_mc.py              # PCA + Hull-White + GBM joint sampler
│   │   └── chronos2_client.py          # AutoGluon Cloud endpoint client (quantiles → joint paths)
│   ├── augmentation/
│   │   ├── __init__.py
│   │   ├── regime_detector.py          # rolling features → w_stress
│   │   └── blender.py                  # tail reweighting + body mixing
│   ├── pricing/
│   │   ├── __init__.py
│   │   ├── book.py                     # sample XCCY book loader
│   │   ├── xccy.py                     # XCCY swap valuation along a path
│   │   └── exposure.py                 # EE / PFE / ES on weighted paths
│   ├── diagnostics/
│   │   ├── __init__.py
│   │   ├── coverage.py                 # regime-conditional band coverage
│   │   ├── tail_dependence.py          # exceedance correlation
│   │   └── distribution.py             # KS / energy-distance helpers
│   ├── plotting/
│   │   ├── __init__.py
│   │   ├── pfe_overlay.py              # baseline vs augmented PFE
│   │   ├── path_samples.py             # joint path fan charts
│   │   └── regime_ribbon.py            # regime indicator strip
│   └── infra/
│       ├── __init__.py
│       └── sagemaker_endpoint.py       # deploy/teardown Chronos-2 via AutoGluon Cloud
│                                       # (S3 helpers deferred to Plan B — the
│                                       #  notebook reads/writes data/curated/
│                                       #  locally; only Lambda tools need S3)
├── tests/
│   ├── conftest.py                     # shared fixtures (fake panel, fake paths, fake book)
│   ├── data/
│   │   ├── test_align.py
│   │   ├── test_regimes.py
│   │   └── test_covariates.py
│   ├── models/
│   │   ├── test_baseline_mc.py
│   │   └── test_chronos2_client.py
│   ├── augmentation/
│   │   ├── test_regime_detector.py
│   │   └── test_blender.py
│   ├── pricing/
│   │   ├── test_xccy.py
│   │   └── test_exposure.py
│   ├── diagnostics/
│   │   ├── test_coverage.py
│   │   ├── test_tail_dependence.py
│   │   └── test_distribution.py
│   └── plotting/
│       └── test_artifacts_render.py
├── notebooks/
│   └── headline_demo.ipynb             # plan deliverable: end-to-end story
├── scripts/
│   ├── snapshot_data.py                # one-shot: pull raw → curated parquet → S3
│   ├── deploy_chronos2_endpoint.py     # one-shot: AutoGluon Cloud endpoint up/down
│   ├── calibrate_headline.py           # part-4: live-endpoint genuine PFE delta → artifact
│   └── benchmark_latency.py            # part-4: nested-MC vs FM timing → artifact
└── docs/
    ├── results/                        # part-4: committed measured artifacts (JSON)
    └── superpowers/
        ├── specs/   (existing spec)
        └── plans/   (this plan)
```

> **Part-4 (Stages 10–12) extends this tree** with `models/nested_mc.py`, `pricing/instruments.py`, the two scripts + `docs/results/` artifacts above, and equity/credit columns across `config.py`, `data/fetch.py`, the book, and the headline fixture. See `2026-05-22-plan-a-quant-pipeline-part-4.md`.

**Each module has one responsibility. Tests live alongside under `tests/` mirroring the source tree.**

---

## Stages

This plan groups tasks into stages. Each stage produces something runnable end-to-end at its conclusion.

- **Stage 0 — Repo bootstrap & data snapshot** (Tasks 1–4)
- **Stage 1 — Regime labeler & feature foundation** (Tasks 5–6)
- **Stage 2 — Baseline parametric MC** (Tasks 7–10)
- **Stage 3 — Chronos-2 client & AutoGluon Cloud deployment** (Tasks 11–14)
- **Stage 4 — Augmentation: regime detector + blender** (Tasks 15–17)
- **Stage 5 — Pricing & exposure (XCCY book, EE/PFE/ES)** (Tasks 18–21)
- **Stage 6 — Diagnostics (coverage, tail dependence, distribution sanity)** (Tasks 22–24)
- **Stage 7 — Plotting helpers** (Tasks 25–27)
- **Stage 8 — Headline demo notebook** (Task 28)
- **Stage 9 — Pin headline numbers + README** (Tasks 29–30)
- **Stage 10 — Equity + credit priced factors** (Tasks 31–35) — *part-4*
- **Stage 11 — Nested-MC benchmark strawman** (Tasks 36–37) — *part-4*
- **Stage 12 — Live headline calibration** (Tasks 38–39) — *part-4*

> Stages 10–12 were added in the 2026-06-04 scope extension; their tasks live in `2026-05-22-plan-a-quant-pipeline-part-4.md`.

---

## Stage 0 — Repo bootstrap & data snapshot

### Task 1: Initialize Python package, dependencies, pytest

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/chronos2_demo/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `.gitignore`**

```gitignore
.venv/
__pycache__/
*.pyc
.ipynb_checkpoints/
data/raw/
data/curated/
.pytest_cache/
.DS_Store
*.egg-info/
dist/
build/
```

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[project]
name = "chronos2-demo"
version = "0.1.0"
description = "Numerix x Chronos-2 PoC quant pipeline"
requires-python = ">=3.11"
dependencies = [
    "numpy>=1.26",
    "scipy>=1.12",
    "pandas>=2.2",
    "scikit-learn>=1.4",
    "matplotlib>=3.8",
    "pyarrow>=15.0",
    "boto3>=1.34",
    "requests>=2.31",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-cov>=4.1", "jupyterlab>=4.0", "ipykernel>=6.29"]
# Heavy; only needed where the Chronos-2 endpoint is deployed/invoked (deploy
# script, headline notebook, Fargate run_chronos2 task) — NOT the core package
# or the thin Lambdas. The hermetic test suite never imports it.
deploy = ["autogluon-cloud>=0.5.0"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --strict-markers"
```

- [ ] **Step 3: Create `src/chronos2_demo/__init__.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 4: Create empty `tests/__init__.py` and minimal `tests/conftest.py`**

`tests/__init__.py`: empty file.

`tests/conftest.py`:
```python
"""Shared pytest fixtures for the chronos2_demo package."""
import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def rng():
    """Deterministic RNG for reproducible tests."""
    return np.random.default_rng(seed=42)


@pytest.fixture
def fake_panel(rng):
    """Small joint FX+rates panel: 5 series, 250 daily obs."""
    dates = pd.bdate_range("2022-01-03", periods=250)
    cols = ["USDEUR", "USDJPY", "USD_2Y", "USD_5Y", "USD_10Y"]
    data = rng.normal(0, 0.005, size=(250, 5)).cumsum(axis=0)
    return pd.DataFrame(data, index=dates, columns=cols)
```

- [ ] **Step 5: Install + smoke-test**

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

Expected: `0 passed in ...` (no tests yet, but pytest runs).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore src/ tests/
git commit -m "chore: bootstrap chronos2-demo Python package

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: Add config module with paths and constants

**Files:**
- Create: `src/chronos2_demo/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
from chronos2_demo import config


def test_data_paths_are_relative_to_repo():
    assert config.DATA_RAW.name == "raw"
    assert config.DATA_CURATED.name == "curated"
    assert config.DATA_RAW.parent.name == "data"


def test_factor_universe_listed():
    fx = set(config.FX_PAIRS)
    assert {"USDEUR", "USDJPY", "USDGBP", "USDCHF", "USDCAD"} == fx
    rates_keys = set(config.RATES_TENORS)
    assert {"2Y", "5Y", "10Y"} == rates_keys
    rates_ccys = set(config.RATES_CCYS)
    assert {"USD", "EUR", "JPY", "GBP"} == rates_ccys


def test_covariates_listed():
    assert set(config.COVARIATES) == {"VIX", "MOVE", "WTI"}


def test_stress_windows_present():
    names = {w["name"] for w in config.STRESS_WINDOWS}
    assert "2022_rate_hike" in names
    assert "2020_covid" in names
```

- [ ] **Step 2: Run test, confirm it fails**

```bash
pytest tests/test_config.py -v
```
Expected: FAIL with `ModuleNotFoundError` or `AttributeError`.

- [ ] **Step 3: Implement `src/chronos2_demo/config.py`**

```python
"""Repo-wide paths and demo constants. Single source of truth."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
DATA_RAW = DATA_DIR / "raw"
DATA_CURATED = DATA_DIR / "curated"

FX_PAIRS = ["USDEUR", "USDJPY", "USDGBP", "USDCHF", "USDCAD"]
RATES_CCYS = ["USD", "EUR", "JPY", "GBP"]
RATES_TENORS = ["2Y", "5Y", "10Y"]
COVARIATES = ["VIX", "MOVE", "WTI"]

# Specific stress windows used in the demo. Pin these so the headline is reproducible.
STRESS_WINDOWS = [
    {"name": "2011_eur_sovereign", "start": "2011-07-01", "end": "2012-01-31"},
    {"name": "2015_chf_unpeg",     "start": "2015-01-01", "end": "2015-03-31"},
    {"name": "2020_covid",         "start": "2020-02-15", "end": "2020-05-31"},
    {"name": "2022_rate_hike",     "start": "2022-03-01", "end": "2022-11-30"},
]

DEFAULT_AS_OF = "2022-06-30"
DEFAULT_HORIZON_DAYS = 252
DEFAULT_N_PATHS = 5_000
DEFAULT_LOOKBACK_DAYS = 504  # ~2y
```

- [ ] **Step 4: Run test, confirm it passes**

```bash
pytest tests/test_config.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/config.py tests/test_config.py
git commit -m "feat(config): add paths and demo constants

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: Data fetchers (FRED rates + ECB FX + covariates)

**Files:**
- Create: `src/chronos2_demo/data/__init__.py`
- Create: `src/chronos2_demo/data/fetch.py`
- Create: `tests/data/__init__.py`
- Create: `tests/data/test_fetch.py`

The fetchers wrap public APIs but the **tests do not hit the network** — they patch `requests.get` so the test suite is hermetic. Real fetches happen via `scripts/snapshot_data.py` (Task 4).

- [ ] **Step 1: Write the failing tests**

`tests/data/__init__.py`: empty.

`tests/data/test_fetch.py`:
```python
import io
from unittest.mock import patch, MagicMock
import pandas as pd
import pytest
from chronos2_demo.data import fetch


def _fake_csv_response(text: str) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.text = text
    resp.raise_for_status = MagicMock()
    return resp


@patch("chronos2_demo.data.fetch.requests.get")
def test_fetch_fred_series_returns_dated_floats(mock_get):
    mock_get.return_value = _fake_csv_response(
        "DATE,DGS10\n2022-01-03,1.63\n2022-01-04,1.66\n2022-01-05,.\n"
    )
    s = fetch.fetch_fred_series("DGS10", api_key="fake")
    assert s.index[0] == pd.Timestamp("2022-01-03")
    assert s.iloc[0] == pytest.approx(1.63)
    assert len(s) == 2  # missing "." rows dropped


@patch("chronos2_demo.data.fetch.requests.get")
def test_fetch_ecb_fx_returns_dated_floats(mock_get):
    mock_get.return_value = _fake_csv_response(
        "TIME_PERIOD,OBS_VALUE\n2022-01-03,1.1308\n2022-01-04,1.1290\n"
    )
    s = fetch.fetch_ecb_fx("EUR", "USD")
    assert len(s) == 2
    assert s.iloc[0] == pytest.approx(1.1308)


@patch("chronos2_demo.data.fetch.requests.get")
def test_fetch_propagates_http_errors(mock_get):
    resp = MagicMock()
    resp.raise_for_status.side_effect = RuntimeError("boom")
    mock_get.return_value = resp
    with pytest.raises(RuntimeError):
        fetch.fetch_fred_series("DGS10", api_key="fake")
```

- [ ] **Step 2: Run tests, confirm they fail**

```bash
pytest tests/data/test_fetch.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `src/chronos2_demo/data/__init__.py` (empty file).**

- [ ] **Step 4: Implement `src/chronos2_demo/data/fetch.py`**

```python
"""Public-source data fetchers. No caching here — see scripts/snapshot_data.py."""
from __future__ import annotations
import io
import pandas as pd
import requests

FRED_CSV_URL = "https://api.stlouisfed.org/fred/series/observations"
ECB_CSV_URL = "https://sdw-wsrest.ecb.europa.eu/service/data/EXR"


def fetch_fred_series(series_id: str, api_key: str) -> pd.Series:
    """Fetch a FRED series as a daily Series indexed by DATE."""
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
    }
    # FRED supports CSV via a different endpoint; we use a stable CSV path:
    csv_url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    resp = requests.get(csv_url, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df.columns = [c.upper() for c in df.columns]
    df = df[df.iloc[:, 1] != "."]
    df["DATE"] = pd.to_datetime(df["DATE"])
    s = df.set_index("DATE").iloc[:, 0].astype(float)
    s.name = series_id
    return s


def fetch_ecb_fx(base_ccy: str, quote_ccy: str) -> pd.Series:
    """Fetch an ECB-published FX rate as quote-per-base."""
    flow_key = f"D.{base_ccy}.{quote_ccy}.SP00.A"
    url = f"{ECB_CSV_URL}/{flow_key}?format=csvdata"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df["TIME_PERIOD"] = pd.to_datetime(df["TIME_PERIOD"])
    s = df.set_index("TIME_PERIOD")["OBS_VALUE"].astype(float)
    s.name = f"{base_ccy}{quote_ccy}"
    return s
```

- [ ] **Step 5: Run tests, confirm they pass**

```bash
pytest tests/data/test_fetch.py -v
```
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add src/chronos2_demo/data/__init__.py src/chronos2_demo/data/fetch.py tests/data/
git commit -m "feat(data): add FRED and ECB fetchers with hermetic tests

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: Panel alignment + curated parquet writer

**Files:**
- Create: `src/chronos2_demo/data/align.py`
- Create: `src/chronos2_demo/data/covariates.py`
- Create: `tests/data/test_align.py`
- Create: `tests/data/test_covariates.py`
- Create: `scripts/snapshot_data.py`

This task locks in the **canonical aligned panel format** used by every downstream module: a pandas DataFrame indexed by business-day Timestamp, columns sorted alphabetically, no NaNs, no duplicate dates.

- [ ] **Step 1: Write the failing alignment tests**

`tests/data/test_align.py`:
```python
import numpy as np
import pandas as pd
import pytest
from chronos2_demo.data import align


def _series(dates, values, name):
    return pd.Series(values, index=pd.to_datetime(dates), name=name)


def test_align_panel_inner_joins_business_days():
    a = _series(["2022-01-03", "2022-01-04", "2022-01-05"], [1, 2, 3], "A")
    b = _series(["2022-01-04", "2022-01-05", "2022-01-06"], [10, 20, 30], "B")
    panel = align.align_panel([a, b])
    assert list(panel.columns) == ["A", "B"]
    assert list(panel.index.strftime("%Y-%m-%d")) == ["2022-01-04", "2022-01-05"]


def test_align_panel_drops_nan_rows():
    a = _series(["2022-01-03", "2022-01-04"], [1, np.nan], "A")
    b = _series(["2022-01-03", "2022-01-04"], [10, 20], "B")
    panel = align.align_panel([a, b])
    assert len(panel) == 1


def test_align_panel_rejects_duplicate_columns():
    a = _series(["2022-01-03"], [1], "A")
    b = _series(["2022-01-03"], [2], "A")
    with pytest.raises(ValueError, match="duplicate"):
        align.align_panel([a, b])


def test_slice_lookback_returns_n_business_days_before_as_of():
    panel = pd.DataFrame(
        {"A": range(10)},
        index=pd.bdate_range("2022-01-03", periods=10),
    )
    out = align.slice_lookback(panel, as_of="2022-01-12", lookback_days=5)
    assert len(out) == 5
    assert out.index[-1] == pd.Timestamp("2022-01-12")
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/data/test_align.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implement `src/chronos2_demo/data/align.py`**

```python
"""Joint alignment of heterogeneous public series into a canonical panel."""
from __future__ import annotations
from typing import Iterable
import pandas as pd


def align_panel(series_list: Iterable[pd.Series]) -> pd.DataFrame:
    """Inner-join Series on business-day index. Drops any row containing NaN.

    Returns a DataFrame indexed by sorted business days, columns sorted by name,
    no NaNs, no duplicate column names.
    """
    series_list = list(series_list)
    names = [s.name for s in series_list]
    if len(set(names)) != len(names):
        raise ValueError(f"duplicate column names: {names}")
    df = pd.concat(series_list, axis=1, join="inner")
    df = df.dropna(how="any")
    df = df.sort_index().sort_index(axis=1)
    df.index = pd.to_datetime(df.index)
    return df


def slice_lookback(panel: pd.DataFrame, as_of: str, lookback_days: int) -> pd.DataFrame:
    """Return the trailing `lookback_days` rows ending on or before `as_of`."""
    as_of_ts = pd.Timestamp(as_of)
    head = panel.loc[:as_of_ts]
    return head.tail(lookback_days)
```

- [ ] **Step 4: Run alignment tests, confirm pass**

```bash
pytest tests/data/test_align.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Write covariates tests**

`tests/data/test_covariates.py`:
```python
import pandas as pd
from unittest.mock import patch
from chronos2_demo.data import covariates


@patch("chronos2_demo.data.covariates._fetch_one")
def test_load_covariates_returns_aligned_frame(mock_fetch):
    idx = pd.bdate_range("2022-01-03", periods=10)
    mock_fetch.side_effect = [
        pd.Series(range(10), index=idx, name="VIX"),
        pd.Series(range(10), index=idx, name="MOVE"),
        pd.Series(range(10), index=idx, name="WTI"),
    ]
    df = covariates.load_covariates()
    assert list(df.columns) == ["MOVE", "VIX", "WTI"]  # alphabetical
    assert len(df) == 10
```

- [ ] **Step 6: Implement `src/chronos2_demo/data/covariates.py`**

```python
"""Exogenous covariates fed only to Chronos-2 (VIX / MOVE / WTI)."""
from __future__ import annotations
import pandas as pd
from chronos2_demo.data import fetch
from chronos2_demo.data.align import align_panel


def _fetch_one(name: str) -> pd.Series:
    """Indirection so tests can patch a single function."""
    fred_map = {"VIX": "VIXCLS", "MOVE": "MOVE", "WTI": "DCOILWTICO"}
    return fetch.fetch_fred_series(fred_map[name], api_key="").rename(name)


def load_covariates() -> pd.DataFrame:
    series = [_fetch_one(n) for n in ("VIX", "MOVE", "WTI")]
    return align_panel(series)
```

- [ ] **Step 7: Run covariate tests, confirm pass**

```bash
pytest tests/data/test_covariates.py -v
```
Expected: 1 passed.

- [ ] **Step 8: Implement `scripts/snapshot_data.py`**

```python
"""One-shot: fetch raw series, build curated parquet panels under data/curated/.

Run: python scripts/snapshot_data.py --fred-api-key $FRED_API_KEY
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
import pandas as pd

from chronos2_demo import config
from chronos2_demo.data import fetch
from chronos2_demo.data.align import align_panel
from chronos2_demo.data.covariates import load_covariates


FRED_RATE_IDS = {
    ("USD", "2Y"): "DGS2", ("USD", "5Y"): "DGS5", ("USD", "10Y"): "DGS10",
    ("EUR", "2Y"): "IRLTLT01EZM156N", ("EUR", "5Y"): "IRLTLT01EZM156N",
    ("EUR", "10Y"): "IRLTLT01EZM156N",
    ("JPY", "2Y"): "INTGSBJPM193N", ("JPY", "5Y"): "INTGSBJPM193N",
    ("JPY", "10Y"): "IRLTLT01JPM156N",
    ("GBP", "2Y"): "INTGSBGBM193N", ("GBP", "5Y"): "INTGSBGBM193N",
    ("GBP", "10Y"): "IRLTLT01GBM156N",
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--fred-api-key", required=True)
    args = p.parse_args()

    config.DATA_CURATED.mkdir(parents=True, exist_ok=True)

    series = []
    for pair in config.FX_PAIRS:
        base, quote = pair[:3], pair[3:]
        s = fetch.fetch_ecb_fx(base, quote).rename(pair)
        series.append(s)

    for ccy in config.RATES_CCYS:
        for tenor in config.RATES_TENORS:
            fred_id = FRED_RATE_IDS[(ccy, tenor)]
            s = fetch.fetch_fred_series(fred_id, args.fred_api_key).rename(f"{ccy}_{tenor}")
            series.append(s)

    panel = align_panel(series)
    panel.to_parquet(config.DATA_CURATED / "panel.parquet")
    print(f"wrote panel: {panel.shape} → {config.DATA_CURATED / 'panel.parquet'}")

    cov = load_covariates()
    cov.to_parquet(config.DATA_CURATED / "covariates.parquet")
    print(f"wrote covariates: {cov.shape}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 9: Commit**

```bash
git add src/chronos2_demo/data/align.py src/chronos2_demo/data/covariates.py \
        tests/data/test_align.py tests/data/test_covariates.py \
        scripts/snapshot_data.py
git commit -m "feat(data): add panel alignment, covariate loader, snapshot script

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Stage 1 — Regime labeler & feature foundation

### Task 5: Deterministic regime labeler

**Files:**
- Create: `src/chronos2_demo/data/regimes.py`
- Create: `tests/data/test_regimes.py`

The regime labeler is a **transparent rule set** the demo must be able to display. It produces both per-date labels (calm/stress) and a continuous `w_stress ∈ [0,1]` used by the augmentation layer.

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np
import pandas as pd
import pytest
from chronos2_demo.data import regimes


def _flat_panel(n=300):
    idx = pd.bdate_range("2020-01-02", periods=n)
    cols = ["USDEUR", "USDJPY", "USD_2Y", "USD_5Y", "USD_10Y"]
    return pd.DataFrame(np.zeros((n, 5)) + 1.0, index=idx, columns=cols)


def _shocked_panel(n=300):
    panel = _flat_panel(n)
    rng = np.random.default_rng(0)
    panel.iloc[200:230] += rng.normal(0, 0.1, size=(30, 5))
    return panel


def test_w_stress_in_unit_interval():
    panel = _shocked_panel()
    w = regimes.w_stress_series(panel, window=20)
    assert (w >= 0).all() and (w <= 1).all()


def test_w_stress_higher_in_shock_window():
    panel = _shocked_panel()
    w = regimes.w_stress_series(panel, window=20)
    calm = w.iloc[50:150].mean()
    shock = w.iloc[210:235].mean()
    assert shock > calm + 0.3


def test_label_thresholds():
    panel = _shocked_panel()
    labels = regimes.label_regimes(panel, window=20)
    assert set(labels.unique()) <= {"calm", "stress"}


def test_w_stress_features_exposed():
    panel = _shocked_panel()
    feats = regimes.regime_features(panel, window=20)
    assert {"rolling_vol", "rates_fx_corr", "vol_of_vol"} <= set(feats.columns)
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/data/test_regimes.py -v
```

- [ ] **Step 3: Implement `src/chronos2_demo/data/regimes.py`**

```python
"""Transparent, rule-based regime labeler.

Produces:
- regime_features(): rolling features over the panel
- w_stress_series(): continuous [0,1] stress weight per date
- label_regimes(): discrete calm/stress label

The rules are intentionally simple so the demo can display the function.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

FX_PREFIX_LEN = 6  # "USDEUR" etc; rates columns contain "_"


def _split_fx_rates(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    rates = panel.filter(regex="_(2Y|5Y|10Y)$")
    fx = panel[[c for c in panel.columns if c not in rates.columns]]
    return fx, rates


def regime_features(panel: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Three rolling features keyed by date."""
    rets = panel.pct_change().dropna(how="all")
    rolling_vol = rets.rolling(window).std().mean(axis=1)
    fx, rates = _split_fx_rates(panel)
    fx_ret = fx.pct_change().mean(axis=1)
    rates_ret = rates.pct_change().mean(axis=1)
    rates_fx_corr = fx_ret.rolling(window).corr(rates_ret).abs()
    vol_of_vol = rolling_vol.rolling(window).std()
    out = pd.DataFrame({
        "rolling_vol": rolling_vol,
        "rates_fx_corr": rates_fx_corr,
        "vol_of_vol": vol_of_vol,
    }).dropna()
    return out


def w_stress_series(panel: pd.DataFrame, window: int = 20) -> pd.Series:
    """Map regime features to w_stress in [0, 1] by historical-percentile rule."""
    feats = regime_features(panel, window=window)
    # Each feature: rank within its own history → [0,1]; combine by mean.
    ranks = feats.rank(pct=True)
    w = ranks.mean(axis=1).clip(0.0, 1.0)
    w.name = "w_stress"
    return w


def label_regimes(panel: pd.DataFrame, window: int = 20, threshold: float = 0.7) -> pd.Series:
    w = w_stress_series(panel, window=window)
    return pd.Series(np.where(w >= threshold, "stress", "calm"), index=w.index, name="regime")
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/data/test_regimes.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/data/regimes.py tests/data/test_regimes.py
git commit -m "feat(regimes): deterministic regime labeler with displayable rules

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: Locked-in panel/path data structures (PathSet dataclass)

**Files:**
- Create: `src/chronos2_demo/types.py`
- Create: `tests/test_types.py`

This task establishes the **single shared data structure** for path sets that every downstream module agrees on. Locking it in early avoids interface drift between Tasks 7–21.

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np
import pandas as pd
import pytest
from chronos2_demo.types import PathSet


def test_pathset_construction_and_shape():
    paths = np.zeros((1000, 252, 5))
    weights = np.ones(1000) / 1000
    series_names = ["USDEUR", "USDJPY", "USD_2Y", "USD_5Y", "USD_10Y"]
    dates = pd.bdate_range("2022-07-01", periods=252)
    ps = PathSet(paths=paths, weights=weights, series=series_names, dates=dates,
                 source="parametric")
    assert ps.n_paths == 1000
    assert ps.horizon == 252
    assert ps.n_series == 5
    assert ps.source == "parametric"


def test_pathset_weights_must_be_positive_and_sum_to_one():
    paths = np.zeros((10, 5, 3))
    series_names = ["A", "B", "C"]
    dates = pd.bdate_range("2022-07-01", periods=5)
    with pytest.raises(ValueError, match="non-negative"):
        PathSet(paths=paths, weights=np.array([1.0]*9 + [-0.1]),
                series=series_names, dates=dates, source="x")
    with pytest.raises(ValueError, match="sum to 1"):
        PathSet(paths=paths, weights=np.full(10, 0.05),
                series=series_names, dates=dates, source="x")


def test_pathset_rejects_shape_mismatch():
    with pytest.raises(ValueError, match="shape"):
        PathSet(paths=np.zeros((10, 5, 3)), weights=np.ones(10)/10,
                series=["A", "B"], dates=pd.bdate_range("2022-07-01", periods=5),
                source="x")
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/test_types.py -v
```

- [ ] **Step 3: Implement `src/chronos2_demo/types.py`**

```python
"""Shared data types every module agrees on. Keep this file small."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
import numpy as np
import pandas as pd

Source = Literal["parametric", "chronos2", "blended", "chronos2_conditional"]


@dataclass(frozen=True)
class PathSet:
    """Shared path-set container.

    paths: ndarray (n_paths, horizon, n_series), in absolute level space.
    weights: ndarray (n_paths,), non-negative, sums to 1.
    series: ordered list of series names, matches paths last axis.
    dates: pandas DatetimeIndex of length `horizon`.
    source: which engine produced these paths.
    """
    paths: np.ndarray
    weights: np.ndarray
    series: list[str]
    dates: pd.DatetimeIndex
    source: Source

    def __post_init__(self) -> None:
        n_paths, horizon, n_series = self.paths.shape
        if self.weights.shape != (n_paths,):
            raise ValueError("weights shape must match n_paths")
        if (self.weights < 0).any():
            raise ValueError("weights must be non-negative")
        if not np.isclose(self.weights.sum(), 1.0):
            raise ValueError("weights must sum to 1")
        if len(self.series) != n_series:
            raise ValueError("shape mismatch: series length must equal paths.shape[-1]")
        if len(self.dates) != horizon:
            raise ValueError("shape mismatch: dates length must equal paths.shape[1]")

    @property
    def n_paths(self) -> int:
        return self.paths.shape[0]

    @property
    def horizon(self) -> int:
        return self.paths.shape[1]

    @property
    def n_series(self) -> int:
        return self.paths.shape[2]
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/test_types.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/types.py tests/test_types.py
git commit -m "feat(types): add PathSet data class shared across modules

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

I've reached a natural pause point. The plan currently covers Stage 0 (Tasks 1-4) and Stage 1 (Tasks 5-6) in full detail. Continuing tasks (Stages 2-9, Tasks 7-30) follow the same TDD pattern.

> _Continued in `2026-05-22-plan-a-quant-pipeline-part-2.md` — see that file for Tasks 7-30 (baseline MC, Chronos-2 client, augmentation, pricing, diagnostics, plotting, headline notebook, README & pinned numbers)._
