# Plan A — Part 2d: Stage 5 — Pricing & Exposure

> **Continuation of** `2026-05-22-plan-a-quant-pipeline-part-2c.md`. Tasks 18–21.

---

## Stage 5 — Pricing & exposure

The "Numerix machinery stand-in." It accepts `(paths, weights)` and produces EE/PFE/ES on a sample cross-currency swap book. The interface is identical for parametric, Chronos-2, and blended inputs — that's what makes the demo's "same engine, different inputs" point land.

Two layers:
- `pricing/xccy.py` — value a single XCCY swap along one path.
- `pricing/exposure.py` — vectorized portfolio MtM across all paths, then EE/PFE/ES.

### Task 18: Sample XCCY book loader

**Files:**
- Create: `src/chronos2_demo/pricing/__init__.py`
- Create: `src/chronos2_demo/pricing/book.py`
- Create: `tests/pricing/__init__.py`
- Create: `tests/pricing/test_book.py`
- Create: `data/sample_book.json` (sample portfolio, committed to repo since it's <2KB)

The book schema is locked here; valuation reads it.

- [ ] **Step 1: Write the failing tests**

`tests/pricing/__init__.py`: empty.

`tests/pricing/test_book.py`:
```python
import json
import pytest
from pathlib import Path
from chronos2_demo.pricing import book as bk


def test_xccy_swap_schema_required_fields(tmp_path):
    swap = {
        "id": "xccy_001",
        "pay_ccy": "EUR",
        "pay_tenor": "5Y",
        "pay_notional": 10_000_000,
        "receive_ccy": "USD",
        "receive_tenor": "5Y",
        "receive_notional": 10_800_000,
        "spot_at_inception_quote_per_base": 1.08,
        "trade_date": "2022-01-03",
        "maturity_date": "2027-01-03",
    }
    parsed = bk.XCCYSwap.from_dict(swap)
    assert parsed.id == "xccy_001"
    assert parsed.pay_ccy == "EUR"
    assert parsed.receive_ccy == "USD"


def test_load_book_reads_json_into_typed_swaps():
    payload = {"swaps": [
        {"id": "a", "pay_ccy": "EUR", "pay_tenor": "5Y", "pay_notional": 1.0,
         "receive_ccy": "USD", "receive_tenor": "5Y", "receive_notional": 1.08,
         "spot_at_inception_quote_per_base": 1.08,
         "trade_date": "2022-01-03", "maturity_date": "2027-01-03"},
        {"id": "b", "pay_ccy": "JPY", "pay_tenor": "10Y", "pay_notional": 1_000_000.0,
         "receive_ccy": "USD", "receive_tenor": "10Y", "receive_notional": 9000.0,
         "spot_at_inception_quote_per_base": 0.009,
         "trade_date": "2022-01-03", "maturity_date": "2032-01-03"},
    ]}
    path = Path("/tmp/_test_book.json")
    path.write_text(json.dumps(payload))
    swaps = bk.load_book(path)
    assert len(swaps) == 2
    assert swaps[0].id == "a"
    assert swaps[1].pay_ccy == "JPY"


def test_default_demo_book_loads():
    swaps = bk.load_book(bk.DEFAULT_BOOK_PATH)
    assert len(swaps) >= 8
    ccy_pairs = {(s.pay_ccy, s.receive_ccy) for s in swaps}
    assert ("EUR", "USD") in ccy_pairs
    assert ("JPY", "USD") in ccy_pairs
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/pricing/test_book.py -v
```

- [ ] **Step 3: Implement files**

`src/chronos2_demo/pricing/__init__.py`: empty.

`src/chronos2_demo/pricing/book.py`:
```python
"""Sample XCCY swap book schema + loader.

Schema is intentionally minimal:
- pay leg in pay_ccy, fixed-notional, single-tenor proxy at the swap rate.
- receive leg mirror in receive_ccy.
- spot_at_inception captures the FX peg locking par on day 0.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json

from chronos2_demo import config

DEFAULT_BOOK_PATH = config.REPO_ROOT / "data" / "sample_book.json"


@dataclass(frozen=True)
class XCCYSwap:
    id: str
    pay_ccy: str
    pay_tenor: str
    pay_notional: float
    receive_ccy: str
    receive_tenor: str
    receive_notional: float
    spot_at_inception_quote_per_base: float
    trade_date: str
    maturity_date: str

    @classmethod
    def from_dict(cls, d: dict) -> "XCCYSwap":
        return cls(**d)


def load_book(path: Path | str = DEFAULT_BOOK_PATH) -> list[XCCYSwap]:
    payload = json.loads(Path(path).read_text())
    return [XCCYSwap.from_dict(s) for s in payload["swaps"]]
```

- [ ] **Step 4: Create `data/sample_book.json`**

```json
{
  "swaps": [
    {"id": "xccy_eur_usd_5y_a", "pay_ccy": "EUR", "pay_tenor": "5Y", "pay_notional": 10000000,
     "receive_ccy": "USD", "receive_tenor": "5Y", "receive_notional": 10800000,
     "spot_at_inception_quote_per_base": 1.08, "trade_date": "2022-01-03", "maturity_date": "2027-01-03"},
    {"id": "xccy_eur_usd_10y", "pay_ccy": "EUR", "pay_tenor": "10Y", "pay_notional": 25000000,
     "receive_ccy": "USD", "receive_tenor": "10Y", "receive_notional": 27000000,
     "spot_at_inception_quote_per_base": 1.08, "trade_date": "2022-01-03", "maturity_date": "2032-01-03"},
    {"id": "xccy_eur_usd_2y_short", "pay_ccy": "USD", "pay_tenor": "2Y", "pay_notional": 5400000,
     "receive_ccy": "EUR", "receive_tenor": "2Y", "receive_notional": 5000000,
     "spot_at_inception_quote_per_base": 1.08, "trade_date": "2022-01-03", "maturity_date": "2024-01-03"},
    {"id": "xccy_jpy_usd_5y", "pay_ccy": "JPY", "pay_tenor": "5Y", "pay_notional": 1000000000,
     "receive_ccy": "USD", "receive_tenor": "5Y", "receive_notional": 8800000,
     "spot_at_inception_quote_per_base": 0.0088, "trade_date": "2022-01-03", "maturity_date": "2027-01-03"},
    {"id": "xccy_jpy_usd_10y", "pay_ccy": "JPY", "pay_tenor": "10Y", "pay_notional": 2000000000,
     "receive_ccy": "USD", "receive_tenor": "10Y", "receive_notional": 17600000,
     "spot_at_inception_quote_per_base": 0.0088, "trade_date": "2022-01-03", "maturity_date": "2032-01-03"},
    {"id": "xccy_gbp_usd_5y", "pay_ccy": "GBP", "pay_tenor": "5Y", "pay_notional": 8000000,
     "receive_ccy": "USD", "receive_tenor": "5Y", "receive_notional": 10800000,
     "spot_at_inception_quote_per_base": 1.35, "trade_date": "2022-01-03", "maturity_date": "2027-01-03"},
    {"id": "xccy_gbp_usd_2y", "pay_ccy": "USD", "pay_tenor": "2Y", "pay_notional": 6750000,
     "receive_ccy": "GBP", "receive_tenor": "2Y", "receive_notional": 5000000,
     "spot_at_inception_quote_per_base": 1.35, "trade_date": "2022-01-03", "maturity_date": "2024-01-03"},
    {"id": "xccy_eur_usd_5y_b", "pay_ccy": "USD", "pay_tenor": "5Y", "pay_notional": 21600000,
     "receive_ccy": "EUR", "receive_tenor": "5Y", "receive_notional": 20000000,
     "spot_at_inception_quote_per_base": 1.08, "trade_date": "2022-01-03", "maturity_date": "2027-01-03"},
    {"id": "xccy_jpy_usd_2y", "pay_ccy": "JPY", "pay_tenor": "2Y", "pay_notional": 500000000,
     "receive_ccy": "USD", "receive_tenor": "2Y", "receive_notional": 4400000,
     "spot_at_inception_quote_per_base": 0.0088, "trade_date": "2022-01-03", "maturity_date": "2024-01-03"},
    {"id": "xccy_gbp_usd_10y", "pay_ccy": "GBP", "pay_tenor": "10Y", "pay_notional": 12000000,
     "receive_ccy": "USD", "receive_tenor": "10Y", "receive_notional": 16200000,
     "spot_at_inception_quote_per_base": 1.35, "trade_date": "2022-01-03", "maturity_date": "2032-01-03"}
  ]
}
```

Note: `data/sample_book.json` is committed (overrides the gitignore `data/` rule). Adjust `.gitignore` to exclude it from being ignored:

- [ ] **Step 5: Update `.gitignore`**

```diff
 data/raw/
 data/curated/
+# Sample book is small and committed for reproducibility:
+!data/sample_book.json
```

Reapply by editing `.gitignore` to add the `!data/sample_book.json` exception line right after the data ignore lines.

- [ ] **Step 6: Run tests, confirm pass**

```bash
pytest tests/pricing/test_book.py -v
```
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add src/chronos2_demo/pricing/__init__.py src/chronos2_demo/pricing/book.py \
        tests/pricing/__init__.py tests/pricing/test_book.py \
        data/sample_book.json .gitignore
git commit -m "feat(pricing): XCCY swap schema, loader, and 10-trade demo book

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 19: XCCY swap valuation along a single path

**Files:**
- Create: `src/chronos2_demo/pricing/xccy.py`
- Create: `tests/pricing/test_xccy.py`

The XCCY swap MtM proxy on this demo uses a closed-form approximation that captures the relevant sensitivities (FX spot move + level shift in the relevant tenor's swap rate). It is **not a full curve build** — that's out of scope per the spec.

**Pricing formula (locked):**

For a swap that pays `pay_notional` in `pay_ccy` and receives `receive_notional` in `receive_ccy`, valued in `receive_ccy`:

```
years_remaining = (maturity_date - valuation_date) / 365.25
mtm = receive_notional * exp(-r_receive * years_remaining)
      - pay_notional * fx_quote_per_base * exp(-r_pay * years_remaining)
```

Where `fx_quote_per_base` is the spot at the valuation date with `receive_ccy` as quote and `pay_ccy` as base (consistent with the panel's `USDXXX` convention; helper handles the inversion). For non-USD legs we report MtM in USD using the relevant FX series.

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np
import pandas as pd
import pytest
from chronos2_demo.pricing import xccy
from chronos2_demo.pricing.book import XCCYSwap


def _swap():
    return XCCYSwap(
        id="t", pay_ccy="EUR", pay_tenor="5Y", pay_notional=10_000_000,
        receive_ccy="USD", receive_tenor="5Y", receive_notional=10_800_000,
        spot_at_inception_quote_per_base=1.08,
        trade_date="2022-01-03", maturity_date="2027-01-03",
    )


def _path_levels():
    """Single path: 252 days of daily levels for the relevant series."""
    idx = pd.bdate_range("2022-01-04", periods=252)
    return pd.DataFrame({
        "USDEUR": np.full(252, 1.08),
        "USD_5Y": np.full(252, 0.025),
        "EUR_5Y": np.full(252, 0.005),
        "USD_2Y": np.full(252, 0.020),
        "EUR_2Y": np.full(252, 0.000),
        "USDJPY": np.full(252, 0.0088),
        "JPY_5Y": np.full(252, 0.000),
        "JPY_2Y": np.full(252, 0.000),
        "JPY_10Y": np.full(252, 0.001),
        "USD_10Y": np.full(252, 0.030),
        "EUR_10Y": np.full(252, 0.010),
        "USDGBP": np.full(252, 1.35),
        "GBP_2Y": np.full(252, 0.010),
        "GBP_5Y": np.full(252, 0.015),
        "GBP_10Y": np.full(252, 0.020),
    }, index=idx)


def test_value_swap_at_inception_is_near_zero():
    swap = _swap()
    levels = _path_levels()
    val = xccy.value_swap_path(swap, levels, ccy_to_usd_series_map=xccy.DEFAULT_FX_MAP)
    # USD MtM at day 0 with rates that make the legs ~par should be small
    # relative to notional.
    notional_usd = swap.pay_notional * 1.08
    assert abs(val[0]) < 0.05 * notional_usd


def test_value_swap_responds_to_fx_shock():
    swap = _swap()
    levels = _path_levels().copy()
    levels["USDEUR"] = 1.20  # EUR appreciates strongly
    val_shocked = xccy.value_swap_path(swap, levels, ccy_to_usd_series_map=xccy.DEFAULT_FX_MAP)
    val_baseline = xccy.value_swap_path(_swap(), _path_levels(),
                                        ccy_to_usd_series_map=xccy.DEFAULT_FX_MAP)
    # Receiving USD, paying EUR → EUR strength reduces USD MtM.
    assert val_shocked[0] < val_baseline[0]


def test_value_swap_responds_to_rates_shock():
    swap = _swap()
    levels = _path_levels().copy()
    levels["USD_5Y"] = 0.060  # large USD rate hike
    val_shocked = xccy.value_swap_path(swap, levels, ccy_to_usd_series_map=xccy.DEFAULT_FX_MAP)
    val_baseline = xccy.value_swap_path(_swap(), _path_levels(),
                                        ccy_to_usd_series_map=xccy.DEFAULT_FX_MAP)
    # Receiving USD fixed → higher discount rate reduces PV of receive leg.
    assert val_shocked[0] < val_baseline[0]


def test_value_swap_returns_full_horizon():
    swap = _swap()
    levels = _path_levels()
    val = xccy.value_swap_path(swap, levels, ccy_to_usd_series_map=xccy.DEFAULT_FX_MAP)
    assert val.shape == (252,)
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/pricing/test_xccy.py -v
```

- [ ] **Step 3: Implement `src/chronos2_demo/pricing/xccy.py`**

```python
"""XCCY swap valuation proxy.

Valuation is in USD: each leg discounted at its own ccy's swap rate at the
relevant tenor, FX-converted to USD via the panel's USD/XXX series.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from chronos2_demo.pricing.book import XCCYSwap

DEFAULT_FX_MAP = {
    "USD": None,         # already USD
    "EUR": "USDEUR",
    "JPY": "USDJPY",
    "GBP": "USDGBP",
    "CHF": "USDCHF",
    "CAD": "USDCAD",
}


def _years_remaining(maturity_date: str, valuation_dates: pd.DatetimeIndex) -> np.ndarray:
    mat = pd.Timestamp(maturity_date)
    delta = (mat - valuation_dates).days
    return np.maximum(delta / 365.25, 0.0)


def _to_usd(ccy: str, ccy_amount: np.ndarray, levels: pd.DataFrame,
            fx_map: dict[str, str | None]) -> np.ndarray:
    if fx_map[ccy] is None:
        return ccy_amount
    series = fx_map[ccy]
    return ccy_amount * levels[series].values


def value_swap_path(
    swap: XCCYSwap,
    levels: pd.DataFrame,
    ccy_to_usd_series_map: dict[str, str | None],
) -> np.ndarray:
    """Return USD MtM at each timestep of `levels` for one path.

    levels: DataFrame of absolute levels at each horizon date.
    ccy_to_usd_series_map: mapping each ccy to the panel column name for
                           USD-quoted FX rate (USDXXX). USD maps to None.
    """
    yrs = _years_remaining(swap.maturity_date, levels.index)
    pay_rate_col = f"{swap.pay_ccy}_{swap.pay_tenor}"
    rec_rate_col = f"{swap.receive_ccy}_{swap.receive_tenor}"
    pay_rate = levels[pay_rate_col].values if pay_rate_col in levels.columns else np.zeros(len(yrs))
    rec_rate = levels[rec_rate_col].values if rec_rate_col in levels.columns else np.zeros(len(yrs))

    # Receive leg PV in receive_ccy then in USD.
    pv_rec_native = swap.receive_notional * np.exp(-rec_rate * yrs)
    pv_rec_usd = _to_usd(swap.receive_ccy, pv_rec_native, levels, ccy_to_usd_series_map)
    # Pay leg PV in pay_ccy then in USD.
    pv_pay_native = swap.pay_notional * np.exp(-pay_rate * yrs)
    pv_pay_usd = _to_usd(swap.pay_ccy, pv_pay_native, levels, ccy_to_usd_series_map)

    return pv_rec_usd - pv_pay_usd
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/pricing/test_xccy.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/pricing/xccy.py tests/pricing/test_xccy.py
git commit -m "feat(pricing): XCCY swap MtM along a single path

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 20: Vectorized portfolio MtM across all paths

**Files:**
- Create: `src/chronos2_demo/pricing/exposure.py` (this task adds `portfolio_mtm` only)
- Create: `tests/pricing/test_exposure_mtm.py`

For PFE we need MtM at every (path, time, swap) cell, then summed across swaps. The function takes a `PathSet` and a list of swaps and returns shape `(n_paths, horizon)` USD MtM tensor.

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np
import pandas as pd
from chronos2_demo.pricing import exposure as ex
from chronos2_demo.pricing.book import XCCYSwap, load_book, DEFAULT_BOOK_PATH
from chronos2_demo.types import PathSet


def _required_series():
    return ["USDEUR", "USDJPY", "USDGBP", "USD_2Y", "USD_5Y", "USD_10Y",
            "EUR_2Y", "EUR_5Y", "EUR_10Y", "JPY_2Y", "JPY_5Y", "JPY_10Y",
            "GBP_2Y", "GBP_5Y", "GBP_10Y"]


def _flat_pathset(n_paths=50, horizon=63):
    series = _required_series()
    n_s = len(series)
    paths = np.tile(
        np.array([1.08, 0.0088, 1.35, 0.020, 0.025, 0.030,
                  0.000, 0.005, 0.010, 0.000, 0.000, 0.001,
                  0.010, 0.015, 0.020]).reshape(1, 1, n_s),
        (n_paths, horizon, 1),
    )
    weights = np.full(n_paths, 1.0 / n_paths)
    dates = pd.bdate_range("2022-07-01", periods=horizon)
    return PathSet(paths=paths, weights=weights, series=series,
                   dates=dates, source="parametric")


def test_portfolio_mtm_shape_matches_paths():
    book = load_book(DEFAULT_BOOK_PATH)
    ps = _flat_pathset()
    mtm = ex.portfolio_mtm(book, ps)
    assert mtm.shape == (ps.n_paths, ps.horizon)


def test_portfolio_mtm_constant_when_paths_are_constant():
    book = load_book(DEFAULT_BOOK_PATH)
    ps = _flat_pathset()
    mtm = ex.portfolio_mtm(book, ps)
    # All paths and timesteps should give identical values.
    assert np.allclose(mtm, mtm[0, 0])


def test_portfolio_mtm_responds_to_fx_shock_on_one_path():
    book = load_book(DEFAULT_BOOK_PATH)
    ps = _flat_pathset(n_paths=10)
    paths = ps.paths.copy()
    paths[0, :, ps.series.index("USDEUR")] = 1.30  # EUR strengthens on path 0
    shocked = PathSet(paths=paths, weights=ps.weights, series=ps.series,
                      dates=ps.dates, source="parametric")
    mtm = ex.portfolio_mtm(book, shocked)
    assert not np.isclose(mtm[0, 0], mtm[1, 0])
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/pricing/test_exposure_mtm.py -v
```

- [ ] **Step 3: Implement `src/chronos2_demo/pricing/exposure.py` (mtm only)**

```python
"""Portfolio MtM and exposure metrics.

This file is split across Tasks 20-21. Task 20 adds portfolio_mtm.
Task 21 adds compute_ee, compute_pfe, compute_es.
"""
from __future__ import annotations
from typing import Sequence
import numpy as np
import pandas as pd

from chronos2_demo.pricing.book import XCCYSwap
from chronos2_demo.pricing.xccy import value_swap_path, DEFAULT_FX_MAP
from chronos2_demo.types import PathSet


def portfolio_mtm(book: Sequence[XCCYSwap], pathset: PathSet) -> np.ndarray:
    """Return (n_paths, horizon) USD MtM tensor for the whole book."""
    n_paths = pathset.n_paths
    horizon = pathset.horizon
    out = np.zeros((n_paths, horizon))
    for i in range(n_paths):
        levels_i = pd.DataFrame(
            pathset.paths[i],
            index=pathset.dates,
            columns=pathset.series,
        )
        for swap in book:
            out[i] += value_swap_path(swap, levels_i, DEFAULT_FX_MAP)
    return out
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/pricing/test_exposure_mtm.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/pricing/exposure.py tests/pricing/test_exposure_mtm.py
git commit -m "feat(pricing): vectorized portfolio MtM across paths

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 21: EE, PFE, ES from a weighted PathSet

**Files:**
- Modify: `src/chronos2_demo/pricing/exposure.py` (append `compute_ee`, `compute_pfe`, `compute_es`, `compute_metrics`)
- Create: `tests/pricing/test_exposure_metrics.py`

Definitions (locked):
- **Exposure** at (path, t) = `max(MtM, 0)` (positive MtM only — counterparty owes us).
- **EE(t)** = weighted mean exposure across paths.
- **PFE(t, q)** = weighted q-quantile of exposure across paths (default q=0.975).
- **ES(t, q)** = weighted mean of exposures above the q-quantile (expected shortfall).

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np
import pandas as pd
import pytest
from chronos2_demo.pricing import exposure as ex
from chronos2_demo.pricing.book import load_book, DEFAULT_BOOK_PATH
from chronos2_demo.types import PathSet


def _pathset_with_known_mtm(mtm: np.ndarray, weights: np.ndarray | None = None):
    """Construct a PathSet where portfolio_mtm would yield `mtm` directly.

    For testing the metrics in isolation we patch out portfolio_mtm; here we
    just need a PathSet with the right shape so the metric functions can be
    invoked with a precomputed MtM tensor.
    """
    n_paths, horizon = mtm.shape
    paths = np.zeros((n_paths, horizon, 1))
    weights = weights if weights is not None else np.full(n_paths, 1.0 / n_paths)
    dates = pd.bdate_range("2022-07-01", periods=horizon)
    return PathSet(paths=paths, weights=weights, series=["x"],
                   dates=dates, source="parametric")


def test_compute_ee_matches_weighted_mean_of_positive_mtm():
    mtm = np.array([[10.0, -5.0],
                    [20.0, 30.0],
                    [-100.0, 40.0]])
    ps = _pathset_with_known_mtm(mtm)
    ee = ex.compute_ee(mtm, ps.weights)
    expected = np.array([(10 + 20) / 3, (0 + 30 + 40) / 3])
    np.testing.assert_allclose(ee, expected)


def test_compute_pfe_at_975_returns_high_quantile():
    rng = np.random.default_rng(0)
    mtm = rng.normal(0, 1, size=(10000, 5))
    ps = _pathset_with_known_mtm(mtm)
    pfe = ex.compute_pfe(mtm, ps.weights, q=0.975)
    # On standard normal, 97.5% quantile of max(z,0) ~ 1.96.
    assert all(1.7 < p < 2.2 for p in pfe)


def test_compute_es_higher_than_pfe():
    rng = np.random.default_rng(0)
    mtm = rng.normal(0, 1, size=(10000, 3))
    ps = _pathset_with_known_mtm(mtm)
    pfe = ex.compute_pfe(mtm, ps.weights, q=0.975)
    es = ex.compute_es(mtm, ps.weights, q=0.975)
    assert all(es[i] > pfe[i] for i in range(3))


def test_compute_metrics_full_pipeline():
    book = load_book(DEFAULT_BOOK_PATH)
    n_paths, horizon = 200, 21
    rng = np.random.default_rng(42)
    series = ["USDEUR", "USDJPY", "USDGBP", "USD_2Y", "USD_5Y", "USD_10Y",
              "EUR_2Y", "EUR_5Y", "EUR_10Y", "JPY_2Y", "JPY_5Y", "JPY_10Y",
              "GBP_2Y", "GBP_5Y", "GBP_10Y"]
    paths = np.zeros((n_paths, horizon, len(series)))
    base = np.array([1.08, 0.0088, 1.35, 0.020, 0.025, 0.030,
                     0.000, 0.005, 0.010, 0.000, 0.000, 0.001,
                     0.010, 0.015, 0.020])
    paths[:] = base
    paths += rng.normal(0, 0.001, size=paths.shape)
    weights = np.full(n_paths, 1.0 / n_paths)
    ps = PathSet(paths=paths, weights=weights, series=series,
                 dates=pd.bdate_range("2022-07-01", periods=horizon),
                 source="parametric")
    metrics = ex.compute_metrics(book, ps)
    assert set(metrics.keys()) == {"ee", "pfe_975", "es_975", "dates"}
    assert metrics["ee"].shape == (horizon,)
    assert metrics["pfe_975"].shape == (horizon,)
    assert metrics["es_975"].shape == (horizon,)
    assert len(metrics["dates"]) == horizon
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/pricing/test_exposure_metrics.py -v
```

- [ ] **Step 3: Append to `src/chronos2_demo/pricing/exposure.py`**

```python
def compute_ee(mtm: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Weighted expected exposure: sum_i w_i * max(MtM_{i,t}, 0)."""
    exposure = np.maximum(mtm, 0.0)
    return weights @ exposure  # (horizon,)


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    """Linear-interpolation weighted quantile."""
    order = np.argsort(values)
    v = values[order]
    w = weights[order]
    cw = np.cumsum(w)
    cw /= cw[-1]
    return float(np.interp(q, cw, v))


def compute_pfe(mtm: np.ndarray, weights: np.ndarray, q: float = 0.975) -> np.ndarray:
    exposure = np.maximum(mtm, 0.0)
    horizon = exposure.shape[1]
    return np.array([_weighted_quantile(exposure[:, t], weights, q) for t in range(horizon)])


def compute_es(mtm: np.ndarray, weights: np.ndarray, q: float = 0.975) -> np.ndarray:
    """Weighted expected shortfall above quantile q."""
    exposure = np.maximum(mtm, 0.0)
    horizon = exposure.shape[1]
    out = np.empty(horizon)
    for t in range(horizon):
        v = exposure[:, t]
        threshold = _weighted_quantile(v, weights, q)
        mask = v >= threshold
        if not mask.any():
            out[t] = threshold
            continue
        w = weights[mask]
        out[t] = float((v[mask] * w).sum() / w.sum())
    return out


def compute_metrics(book: Sequence[XCCYSwap], pathset: PathSet,
                    q: float = 0.975) -> dict:
    mtm = portfolio_mtm(book, pathset)
    return {
        "ee":      compute_ee(mtm, pathset.weights),
        "pfe_975": compute_pfe(mtm, pathset.weights, q=q),
        "es_975":  compute_es(mtm, pathset.weights, q=q),
        "dates":   pathset.dates,
    }
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/pricing/test_exposure_metrics.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/pricing/exposure.py tests/pricing/test_exposure_metrics.py
git commit -m "feat(pricing): EE, PFE, ES from weighted PathSet

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

> _Continue with `2026-05-22-plan-a-quant-pipeline-part-3.md` (Stages 6–9: diagnostics, plotting, headline notebook, README & pinned numbers, Tasks 22–30)._
