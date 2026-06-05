# Plan A — Part 4: Stages 10–12 — Cross-asset factors, nested-MC benchmark, live calibration

> **Continuation of** `2026-05-22-plan-a-quant-pipeline-part-3c.md`. Tasks 31–40.
>
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the quant core for the three sanctioned 2026-06-04 scope additions (see the spec's "2026-06-04 scope-extension note"): (1) equity + credit as priced factors, (2) a nested-MC benchmark strawman, (3) a live-endpoint headline calibration script — plus the latency benchmark script.

**Architecture:** Add equity (SPX, NIKKEI225) and credit (US_IG_OAS, US_HY_OAS) series to the jointly-modeled panel; both engines consume them unchanged (PCA is dimension-agnostic; the copula is dimension-agnostic). Two new closed-form instruments (equity forward, CDS-protection proxy) make equity/credit move EE/PFE/ES. A small real `models/nested_mc.py` provides the benchmark reference engine. Two non-test scripts record committed JSON artifacts under `docs/results/`.

**Tech Stack:** Python 3.11, numpy, scipy, pandas, scikit-learn, pytest. No new dependencies.

**Reference spec:** `docs/superpowers/specs/2026-05-22-numerix-chronos2-poc-design.md` (§4, §6, §8, §11).

---

> **Before Task 31:** read the **Engineering Discipline** section in `CLAUDE.md`. Plan-A-specific reinforcements (asymmetric covariates, hermetic tests, pinned headline numbers) still apply. Two new reinforcements for this part:
> - **The equity/credit series are priced factors, not covariates.** They go in the panel both engines read — *not* in `data/covariates.py` (which stays VIX/MOVE/WTI, Chronos-2-only).
> - **Nested MC is a benchmark reference, never the demo pricing path.** Keep it out of `pricing/exposure.py`'s `compute_metrics`; the demo still prices closed-form.

---

## File Structure (locked in before tasks)

```
src/chronos2_demo/
├── config.py                       # MODIFY: add EQUITY_INDICES, CREDIT_SPREADS
├── data/
│   ├── fetch.py                    # MODIFY: add fetch_credit_oas (FRED OAS ids)
│   └── regimes.py                  # MODIFY: _split_fx_rates → config-driven classifier
├── pricing/
│   ├── book.py                     # MODIFY: EquityForward + CDSProtection dataclasses + loader
│   ├── instruments.py              # CREATE: closed-form equity-forward + CDS-proxy valuation
│   └── exposure.py                 # MODIFY: portfolio_mtm dispatches by instrument type
└── models/
    └── nested_mc.py                # CREATE: benchmark nested-MC exposure engine

data/sample_book.json               # MODIFY: add 1 equity forward + 1 CDS proxy
scripts/
├── snapshot_data.py                # MODIFY: fetch + append equity/credit columns
├── calibrate_headline.py           # CREATE: live-endpoint genuine PFE delta → artifact
└── benchmark_latency.py            # CREATE: nested-MC vs FM timing → artifact
docs/results/
├── headline_calibration.json       # CREATE (committed; placeholder until first live run)
└── latency_benchmark.json          # CREATE (committed; placeholder until first run)
tests/
├── fixtures/build_headline_panel.py  # MODIFY: add 4 cross-asset columns
├── pricing/test_instruments.py     # CREATE
├── pricing/test_book.py            # MODIFY: assert cross-asset instruments load
├── data/test_regimes.py           # MODIFY: assert equity/credit excluded from corr
└── models/test_nested_mc.py        # CREATE
```

---

## Stage 10 — Equity + credit priced factors

The cross-asset universe. The series enter the panel both engines read; two instruments make them move exposure; the regime detector is corrected so the new columns don't corrupt its FX/rates correlation feature.

### Task 31: Add equity + credit series to config and fetchers

**Files:**
- Modify: `src/chronos2_demo/config.py`
- Modify: `src/chronos2_demo/data/fetch.py`
- Test: `tests/data/test_fetch.py` (modify), `tests/test_config.py` (modify)

The four new columns are `SPX`, `NIKKEI225` (equity index levels) and `US_IG_OAS`, `US_HY_OAS` (credit option-adjusted spreads, in percent). All four come from FRED (`SP500`, `NIKKEI225`, `BAMLC0A0CM`, `BAMLH0A0HYM2`), so the existing `fetch_fred_series` covers equity; credit gets a thin named wrapper for clarity and a single patch point (mirrors `covariates._fetch_one`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:
```python
def test_equity_and_credit_factor_universe():
    from chronos2_demo import config
    assert config.EQUITY_INDICES == ["SPX", "NIKKEI225"]
    assert config.CREDIT_SPREADS == ["US_IG_OAS", "US_HY_OAS"]
    # No overlap with FX / rates / covariates.
    overlap = set(config.EQUITY_INDICES + config.CREDIT_SPREADS) & (
        set(config.FX_PAIRS) | set(config.COVARIATES)
    )
    assert overlap == set()
```

Append to `tests/data/test_fetch.py`:
```python
def test_fetch_credit_oas_maps_names_to_fred_ids(monkeypatch):
    from chronos2_demo.data import fetch
    captured = {}

    def fake_fred(series_id, api_key):
        captured["id"] = series_id
        import pandas as pd
        return pd.Series([1.2, 1.3], index=pd.to_datetime(["2022-06-01", "2022-06-02"]),
                         name=series_id)

    monkeypatch.setattr(fetch, "fetch_fred_series", fake_fred)
    s = fetch.fetch_credit_oas("US_IG_OAS", api_key="k")
    assert captured["id"] == "BAMLC0A0CM"
    assert s.name == "US_IG_OAS"
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/test_config.py::test_equity_and_credit_factor_universe tests/data/test_fetch.py::test_fetch_credit_oas_maps_names_to_fred_ids -v
```
Expected: FAIL (`AttributeError: module ... has no attribute 'EQUITY_INDICES'` / `'fetch_credit_oas'`).

- [ ] **Step 3: Implement**

In `src/chronos2_demo/config.py`, after the `COVARIATES` line:
```python
# Cross-asset priced factors (added 2026-06-04). Modeled jointly by BOTH engines
# — NOT covariates. See spec §4.
EQUITY_INDICES = ["SPX", "NIKKEI225"]
CREDIT_SPREADS = ["US_IG_OAS", "US_HY_OAS"]
```

In `src/chronos2_demo/data/fetch.py`, append:
```python
_CREDIT_FRED_IDS = {"US_IG_OAS": "BAMLC0A0CM", "US_HY_OAS": "BAMLH0A0HYM2"}


def fetch_credit_oas(name: str, api_key: str) -> pd.Series:
    """Fetch an ICE BofA OAS series from FRED, renamed to the panel column."""
    return fetch_fred_series(_CREDIT_FRED_IDS[name], api_key=api_key).rename(name)
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/test_config.py tests/data/test_fetch.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/config.py src/chronos2_demo/data/fetch.py tests/test_config.py tests/data/test_fetch.py
git commit -m "feat(data): add equity + credit series to the cross-asset factor universe

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 32: Fix the regime FX/rates split for the wider universe

**Files:**
- Modify: `src/chronos2_demo/data/regimes.py:17-20` (`_split_fx_rates`)
- Test: `tests/data/test_regimes.py` (modify)

`_split_fx_rates` currently does a *binary* split: rates = columns matching `_(2Y|5Y|10Y)$`, FX = everything else. With equity/credit in the panel, `SPX`/`US_IG_OAS` would fall into the FX bucket and corrupt `rates_fx_corr`. Fix: FX is exactly the configured `FX_PAIRS`; rates is the tenor regex; equity/credit are excluded from this correlation feature (they still feed `rolling_vol`, which uses the whole panel). The feature set stays at 3 — faithful to "intentionally simple."

- [ ] **Step 1: Write the failing test**

Append to `tests/data/test_regimes.py`:
```python
def test_split_excludes_equity_and_credit_from_fx_rates():
    idx = pd.bdate_range("2020-01-02", periods=300)
    cols = ["USDEUR", "USDJPY", "USD_2Y", "USD_5Y", "SPX", "US_IG_OAS"]
    panel = pd.DataFrame(np.ones((300, 6)), index=idx, columns=cols)
    fx, rates = regimes._split_fx_rates(panel)
    assert list(fx.columns) == ["USDEUR", "USDJPY"]
    assert list(rates.columns) == ["USD_2Y", "USD_5Y"]
    # Equity/credit are in neither bucket.
    assert "SPX" not in fx.columns and "SPX" not in rates.columns
    assert "US_IG_OAS" not in fx.columns and "US_IG_OAS" not in rates.columns


def test_regime_features_still_three_columns_with_cross_asset():
    idx = pd.bdate_range("2020-01-02", periods=300)
    cols = ["USDEUR", "USD_2Y", "SPX", "US_HY_OAS"]
    rng = np.random.default_rng(0)
    panel = pd.DataFrame(1.0 + rng.normal(0, 0.01, size=(300, 4)).cumsum(axis=0),
                         index=idx, columns=cols)
    feats = regimes.regime_features(panel, window=20)
    assert {"rolling_vol", "rates_fx_corr", "vol_of_vol"} == set(feats.columns)
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/data/test_regimes.py::test_split_excludes_equity_and_credit_from_fx_rates -v
```
Expected: FAIL (`SPX`/`US_IG_OAS` land in `fx.columns`).

- [ ] **Step 3: Implement**

Replace `_split_fx_rates` in `src/chronos2_demo/data/regimes.py` (the `FX_PREFIX_LEN` constant on line 14 becomes unused — delete it too):
```python
from chronos2_demo import config


def _split_fx_rates(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split panel into (fx, rates) for the correlation feature.

    FX is exactly the configured FX_PAIRS present in the panel; rates is the
    tenor-suffixed columns. Equity/credit (and anything else) are excluded —
    they feed rolling_vol via the full panel but not rates_fx_corr.
    """
    rates = panel.filter(regex="_(2Y|5Y|10Y)$")
    fx = panel[[c for c in panel.columns if c in config.FX_PAIRS]]
    return fx, rates
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/data/test_regimes.py -v
```
Expected: PASS (all prior regime tests still green — the 5-series fixtures have no equity/credit, so behavior is unchanged for them).

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/data/regimes.py tests/data/test_regimes.py
git commit -m "fix(regimes): exclude equity/credit from the FX-rates correlation feature

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 33: Closed-form equity-forward and CDS-protection valuation

**Files:**
- Create: `src/chronos2_demo/pricing/instruments.py`
- Test: `tests/pricing/test_instruments.py`

Two closed-form, level-driven proxies in the same style as `xccy.value_swap_path` — each returns USD MtM at every timestep of a `levels` DataFrame for one path.

- **Equity forward:** `MtM_t = direction · notional · (S_t − K) · fx_to_usd`, where `S` is the equity index column, `K` the strike (default `S` at the first level row), `fx_to_usd` the FX series mapping the index's quote ccy to USD (1.0 for USD-quoted SPX; `USDJPY` for NIKKEI225).
- **CDS protection:** `MtM_t = direction · notional · (spread_t − spread_0) · rpv01`, where `spread` is an OAS column **in percent**, converted to fraction (`/100`), and `rpv01` is a risky annuity constant (years). Protection buyer (`direction=+1`) gains as spreads widen.

- [ ] **Step 1: Write the failing tests**

`tests/pricing/test_instruments.py`:
```python
import numpy as np
import pandas as pd
import pytest
from chronos2_demo.pricing import instruments as ins


def _levels():
    idx = pd.bdate_range("2022-07-01", periods=3)
    return pd.DataFrame(
        {"SPX": [4000.0, 4100.0, 3900.0],
         "USDJPY": [0.0072, 0.0072, 0.0072],
         "NIKKEI225": [28000.0, 28000.0, 28000.0],
         "US_IG_OAS": [1.20, 1.30, 1.50]},  # percent
        index=idx,
    )


def test_equity_forward_usd_quoted_pnl():
    lv = _levels()
    # K defaults to first level (4000); long 10 units.
    mtm = ins.value_equity_forward_path(
        ins.EquityForward(id="e1", index="SPX", quote_ccy="USD", strike=None,
                          notional=10.0, direction=1),
        lv, {"USD": None, "JPY": "USDJPY"},
    )
    assert mtm[0] == pytest.approx(0.0)
    assert mtm[1] == pytest.approx(10.0 * (4100.0 - 4000.0))
    assert mtm[2] == pytest.approx(10.0 * (3900.0 - 4000.0))


def test_equity_forward_fx_converts_when_not_usd():
    lv = _levels()
    mtm = ins.value_equity_forward_path(
        ins.EquityForward(id="e2", index="NIKKEI225", quote_ccy="JPY", strike=27000.0,
                          notional=2.0, direction=1),
        lv, {"USD": None, "JPY": "USDJPY"},
    )
    # (28000 - 27000) * 2 units * 0.0072 USD/JPY, constant across steps.
    assert mtm[0] == pytest.approx(2.0 * (28000.0 - 27000.0) * 0.0072)


def test_cds_protection_gains_as_spread_widens():
    lv = _levels()
    mtm = ins.value_cds_protection_path(
        ins.CDSProtection(id="c1", spread_series="US_IG_OAS", notional=1_000_000.0,
                          rpv01=4.5, direction=1),
        lv,
    )
    assert mtm[0] == pytest.approx(0.0)
    # (1.50% - 1.20%) / 100 * 1e6 * 4.5
    assert mtm[2] == pytest.approx((1.50 - 1.20) / 100.0 * 1_000_000.0 * 4.5)
    assert mtm[2] > mtm[1] > mtm[0]
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/pricing/test_instruments.py -v
```
Expected: FAIL (`ModuleNotFoundError: chronos2_demo.pricing.instruments`).

- [ ] **Step 3: Implement**

`src/chronos2_demo/pricing/instruments.py`:
```python
"""Closed-form cross-asset instrument valuation (equity forward, CDS protection).

Same contract as pricing/xccy.value_swap_path: given a per-path `levels`
DataFrame (absolute levels at each horizon date), return USD MtM per timestep.
These make the equity/credit factors move EE/PFE/ES. See spec §4.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class EquityForward:
    id: str
    index: str            # panel column for the equity index level
    quote_ccy: str        # ccy the index is quoted in (USD, JPY, ...)
    strike: float | None  # K; None => use S at the first level row
    notional: float       # units of the index
    direction: int        # +1 long, -1 short

    @classmethod
    def from_dict(cls, d: dict) -> "EquityForward":
        return cls(id=d["id"], index=d["index"], quote_ccy=d["quote_ccy"],
                   strike=d.get("strike"), notional=float(d["notional"]),
                   direction=int(d.get("direction", 1)))


@dataclass(frozen=True)
class CDSProtection:
    id: str
    spread_series: str    # panel column for the OAS, in PERCENT
    notional: float
    rpv01: float          # risky annuity (years)
    direction: int        # +1 protection buyer (gains as spread widens)

    @classmethod
    def from_dict(cls, d: dict) -> "CDSProtection":
        return cls(id=d["id"], spread_series=d["spread_series"],
                   notional=float(d["notional"]), rpv01=float(d["rpv01"]),
                   direction=int(d.get("direction", 1)))


def value_equity_forward_path(
    fwd: EquityForward, levels: pd.DataFrame, ccy_to_usd_series_map: dict[str, str | None]
) -> np.ndarray:
    s = levels[fwd.index].to_numpy(dtype=float)
    k = s[0] if fwd.strike is None else float(fwd.strike)
    pnl_ccy = fwd.direction * fwd.notional * (s - k)
    fx_series = ccy_to_usd_series_map.get(fwd.quote_ccy)
    if fx_series is None:
        return pnl_ccy
    return pnl_ccy * levels[fx_series].to_numpy(dtype=float)


def value_cds_protection_path(cds: CDSProtection, levels: pd.DataFrame) -> np.ndarray:
    spread = levels[cds.spread_series].to_numpy(dtype=float) / 100.0  # percent → fraction
    return cds.direction * cds.notional * (spread - spread[0]) * cds.rpv01
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/pricing/test_instruments.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/pricing/instruments.py tests/pricing/test_instruments.py
git commit -m "feat(pricing): closed-form equity-forward and CDS-protection valuation

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 34: Wire cross-asset instruments into the book and portfolio MtM

**Files:**
- Modify: `src/chronos2_demo/pricing/book.py`
- Modify: `src/chronos2_demo/pricing/exposure.py:16-29` (`portfolio_mtm`) and `:71-79` (`compute_metrics`)
- Modify: `data/sample_book.json`
- Test: `tests/pricing/test_book.py` (modify), `tests/pricing/test_exposure_mtm.py` (modify), `tests/pricing/test_exposure_metrics.py` (modify)

`load_book` returns XCCY swaps today. Generalize it to also parse `equity_forwards` and `cds_protection` blocks, make `portfolio_mtm` dispatch by instrument type so all three contribute to the USD MtM tensor, and thread the same optional instruments through `compute_metrics` so the clean public API (used by the notebook, the calibration script, AND the agent's `price_book` Lambda) prices the whole cross-asset book. The `ccy_to_usd_series_map` is `DEFAULT_FX_MAP` (already imported by exposure).

- [ ] **Step 1: Write the failing tests**

Append to `tests/pricing/test_book.py`:
```python
def test_load_book_parses_cross_asset_instruments():
    from chronos2_demo.pricing import book as bk
    swaps, equities, cds = bk.load_cross_asset_book(bk.DEFAULT_BOOK_PATH)
    assert len(swaps) >= 8
    assert len(equities) >= 1
    assert len(cds) >= 1
    assert equities[0].index in {"SPX", "NIKKEI225"}
    assert cds[0].spread_series in {"US_IG_OAS", "US_HY_OAS"}
```

Append to `tests/pricing/test_exposure_mtm.py`:
```python
def test_portfolio_mtm_includes_equity_and_credit(rng):
    import numpy as np, pandas as pd
    from chronos2_demo.types import PathSet
    from chronos2_demo.pricing import book as bk, exposure
    series = ["USDEUR", "USDJPY", "USD_5Y", "EUR_5Y", "SPX", "NIKKEI225", "US_IG_OAS"]
    dates = pd.bdate_range("2022-07-01", periods=10)
    paths = np.abs(rng.normal(1.0, 0.05, size=(20, 10, len(series)))) + 0.5
    ps = PathSet(paths=paths, weights=np.full(20, 1/20), series=series,
                 dates=dates, source="parametric")
    swaps, equities, cds = bk.load_cross_asset_book(bk.DEFAULT_BOOK_PATH)
    mtm = exposure.portfolio_mtm(swaps, ps, equity_forwards=equities, cds_protection=cds)
    assert mtm.shape == (20, 10)
    # Dropping equity+credit changes the MtM (they contribute).
    mtm_swaps_only = exposure.portfolio_mtm(swaps, ps)
    assert not np.allclose(mtm, mtm_swaps_only)
```

Append to `tests/pricing/test_exposure_metrics.py`:
```python
def test_compute_metrics_threads_cross_asset_instruments(rng):
    import numpy as np, pandas as pd
    from chronos2_demo.types import PathSet
    from chronos2_demo.pricing import book as bk, exposure
    series = ["USDEUR", "USDJPY", "USD_5Y", "EUR_5Y", "SPX", "NIKKEI225", "US_IG_OAS"]
    dates = pd.bdate_range("2022-07-01", periods=8)
    paths = np.abs(rng.normal(1.0, 0.05, size=(30, 8, len(series)))) + 0.5
    ps = PathSet(paths=paths, weights=np.full(30, 1/30), series=series,
                 dates=dates, source="parametric")
    swaps, eq, cds = bk.load_cross_asset_book(bk.DEFAULT_BOOK_PATH)
    m_full = exposure.compute_metrics(swaps, ps, equity_forwards=eq, cds_protection=cds)
    m_swaps = exposure.compute_metrics(swaps, ps)
    assert m_full["pfe_975"].shape == (8,)
    assert not np.allclose(m_full["pfe_975"], m_swaps["pfe_975"])
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/pricing/test_book.py::test_load_book_parses_cross_asset_instruments tests/pricing/test_exposure_mtm.py::test_portfolio_mtm_includes_equity_and_credit tests/pricing/test_exposure_metrics.py::test_compute_metrics_threads_cross_asset_instruments -v
```
Expected: FAIL (`AttributeError: ... 'load_cross_asset_book'`; `compute_metrics() got an unexpected keyword argument`).

- [ ] **Step 3: Implement**

In `src/chronos2_demo/pricing/book.py`, add the import and loader (keep `load_book` unchanged for back-compat):
```python
from chronos2_demo.pricing.instruments import EquityForward, CDSProtection


def load_cross_asset_book(
    path: Path | str = DEFAULT_BOOK_PATH,
) -> tuple[list[XCCYSwap], list[EquityForward], list[CDSProtection]]:
    """Parse swaps + optional equity_forwards + cds_protection blocks."""
    payload = json.loads(Path(path).read_text())
    swaps = [XCCYSwap.from_dict(s) for s in payload.get("swaps", [])]
    equities = [EquityForward.from_dict(e) for e in payload.get("equity_forwards", [])]
    cds = [CDSProtection.from_dict(c) for c in payload.get("cds_protection", [])]
    return swaps, equities, cds
```

In `src/chronos2_demo/pricing/exposure.py`, replace `portfolio_mtm` (lines 16-29). Add the imports at the top of the function's use site:
```python
from chronos2_demo.pricing.instruments import (
    EquityForward, CDSProtection, value_equity_forward_path, value_cds_protection_path,
)


def portfolio_mtm(
    book: Sequence[XCCYSwap],
    pathset: PathSet,
    equity_forwards: Sequence[EquityForward] = (),
    cds_protection: Sequence[CDSProtection] = (),
) -> np.ndarray:
    """Return (n_paths, horizon) USD MtM tensor for the whole cross-asset book."""
    n_paths = pathset.n_paths
    horizon = pathset.horizon
    out = np.zeros((n_paths, horizon))
    for i in range(n_paths):
        levels_i = pd.DataFrame(
            pathset.paths[i], index=pathset.dates, columns=pathset.series,
        )
        for swap in book:
            out[i] += value_swap_path(swap, levels_i, DEFAULT_FX_MAP)
        for fwd in equity_forwards:
            out[i] += value_equity_forward_path(fwd, levels_i, DEFAULT_FX_MAP)
        for cds in cds_protection:
            out[i] += value_cds_protection_path(cds, levels_i)
    return out
```

Also update `compute_metrics` (lines 71-79) to accept and forward the same optional instruments:
```python
def compute_metrics(book: Sequence[XCCYSwap], pathset: PathSet,
                    q: float = 0.975,
                    equity_forwards: Sequence[EquityForward] = (),
                    cds_protection: Sequence[CDSProtection] = ()) -> dict:
    mtm = portfolio_mtm(book, pathset, equity_forwards=equity_forwards,
                        cds_protection=cds_protection)
    return {
        "ee":      compute_ee(mtm, pathset.weights),
        "pfe_975": compute_pfe(mtm, pathset.weights, q=q),
        "es_975":  compute_es(mtm, pathset.weights, q=q),
        "dates":   pathset.dates,
    }
```

In `data/sample_book.json`, add two sibling keys after the `"swaps"` array (keep `swaps` as-is):
```json
  "equity_forwards": [
    {"id": "eqf_spx_long", "index": "SPX", "quote_ccy": "USD", "strike": null,
     "notional": 2000, "direction": 1}
  ],
  "cds_protection": [
    {"id": "cds_ig_buy", "spread_series": "US_IG_OAS", "notional": 50000000,
     "rpv01": 4.5, "direction": 1}
  ]
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/pricing/ -v
```
Expected: PASS (existing `compute_metrics`/`portfolio_mtm` swap-only calls still work — the new params default to empty).

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/pricing/book.py src/chronos2_demo/pricing/exposure.py data/sample_book.json tests/pricing/test_book.py tests/pricing/test_exposure_mtm.py
git commit -m "feat(pricing): cross-asset book loader + equity/credit in portfolio MtM

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 35: Regenerate the headline regression fixture with cross-asset columns

**Files:**
- Modify: `tests/fixtures/build_headline_panel.py`
- Modify: `tests/fixtures/headline_panel.parquet` (regenerated artifact)
- Modify: `tests/test_headline_numbers.py` (book loader call)

The frozen synthetic panel must carry the 4 new columns so the cross-asset book prices against it. The fake-endpoint quantile spread is unchanged; this stays a *plumbing* guard (the genuine number is Task 39). The `_FakeEndpoint` already emits one quantile block per `item_id` in the request frame, so it adapts to the wider panel with no change.

- [ ] **Step 1: Update the fixture builder**

In `tests/fixtures/build_headline_panel.py`, extend `cols` and `base` (append after the existing GBP rows):
```python
    cols = ["USDEUR", "USDJPY", "USDGBP",
            "USD_2Y", "USD_5Y", "USD_10Y",
            "EUR_2Y", "EUR_5Y", "EUR_10Y",
            "JPY_2Y", "JPY_5Y", "JPY_10Y",
            "GBP_2Y", "GBP_5Y", "GBP_10Y",
            "SPX", "NIKKEI225", "US_IG_OAS", "US_HY_OAS"]
    base = np.array([1.08, 0.0088, 1.35,
                     0.020, 0.025, 0.030,
                     0.000, 0.005, 0.010,
                     0.000, 0.000, 0.001,
                     0.010, 0.015, 0.020,
                     4000.0, 28000.0, 1.20, 4.00])
```
The `raw[400:430] += rng.normal(0, 0.02, ...)` stress injection scales each column by its own noise, but the absolute levels for SPX/NIKKEI are large — change the stress injection to be relative so it perturbs every column meaningfully:
```python
    raw = base + rng.normal(0, 0.001, size=(n_obs, len(cols))).cumsum(axis=0) * 0.001 * base
    # Inject a stress window so w_stress at as_of is meaningfully > 0.
    raw[400:430] += rng.normal(0, 0.02, size=(30, len(cols))) * base
```

- [ ] **Step 2: Regenerate the fixture**

```bash
python tests/fixtures/build_headline_panel.py
```
Expected: `wrote .../headline_panel.parquet: (600, 19)`.

- [ ] **Step 3: Point the headline test at the cross-asset book**

In `tests/test_headline_numbers.py`, replace the `book.load_book(...)` line and thread the instruments through both `portfolio_mtm` (for the blend's tail PnL) and `compute_metrics` (for the PFE). Replace:
```python
    swaps = book.load_book(book.DEFAULT_BOOK_PATH)
    par_term = exposure.portfolio_mtm(swaps, par)[:, -1]
    chr_term = exposure.portfolio_mtm(swaps, chr_)[:, -1]
    blended = blender.blend_paths(par, chr_, par_term, chr_term, w_stress=snap.w_stress)

    base_pfe = exposure.compute_metrics(swaps, par)["pfe_975"][-1]
    aug_pfe = exposure.compute_metrics(swaps, blended)["pfe_975"][-1]
```
with:
```python
    swaps, equities, cds = book.load_cross_asset_book(book.DEFAULT_BOOK_PATH)
    par_term = exposure.portfolio_mtm(swaps, par, equities, cds)[:, -1]
    chr_term = exposure.portfolio_mtm(swaps, chr_, equities, cds)[:, -1]
    blended = blender.blend_paths(par, chr_, par_term, chr_term, w_stress=snap.w_stress)

    base_pfe = exposure.compute_metrics(
        swaps, par, equity_forwards=equities, cds_protection=cds)["pfe_975"][-1]
    aug_pfe = exposure.compute_metrics(
        swaps, blended, equity_forwards=equities, cds_protection=cds)["pfe_975"][-1]
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/test_headline_numbers.py -v
```
Expected: PASS (direction `aug_pfe >= base_pfe` and the sanity band still hold; if the band fails, **stop and report** — do not loosen it without surfacing, per CLAUDE.md).

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/build_headline_panel.py tests/fixtures/headline_panel.parquet tests/test_headline_numbers.py
git commit -m "test(headline): regenerate fixture + price cross-asset book in the regression

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Stage 11 — Nested-MC benchmark strawman

A small but real nested Monte Carlo exposure engine — outer factor scenarios × inner revaluation sub-paths at each exposure date. It exists **only** as the latency benchmark reference; it is never wired into `compute_metrics`. The hermetic test pins correctness (zero inner volatility ⇒ nested PFE ≈ closed-form PFE), never timing.

### Task 36: Nested-MC exposure engine

**Files:**
- Create: `src/chronos2_demo/models/nested_mc.py`
- Test: `tests/models/test_nested_mc.py`

At each exposure date `t`, take the outer level state, spawn `n_inner` Gaussian revaluation sub-paths (a one-step GBM bump per series with vol `inner_vol`), reprice the book on each, and take the mean as the simulated PV at `t`. PFE is the quantile of `max(PV,0)` across outer scenarios. With `inner_vol=0` every inner sub-path equals the outer state, so the mean PV collapses to the closed-form `portfolio_mtm` value — that's the correctness pin.

- [ ] **Step 1: Write the failing test**

`tests/models/test_nested_mc.py`:
```python
import numpy as np
import pandas as pd
import pytest
from chronos2_demo.types import PathSet
from chronos2_demo.pricing import book as bk, exposure
from chronos2_demo.models import nested_mc


def _pathset(rng, n_paths=40, horizon=6):
    series = ["USDEUR", "USDJPY", "USD_5Y", "EUR_5Y", "SPX", "NIKKEI225", "US_IG_OAS"]
    dates = pd.bdate_range("2022-07-01", periods=horizon)
    paths = np.abs(rng.normal(1.0, 0.03, size=(n_paths, horizon, len(series)))) + 0.5
    return PathSet(paths=paths, weights=np.full(n_paths, 1/n_paths),
                   series=series, dates=dates, source="parametric")


def test_nested_pfe_matches_closed_form_when_inner_vol_zero(rng):
    ps = _pathset(rng)
    swaps, eq, cds = bk.load_cross_asset_book(bk.DEFAULT_BOOK_PATH)
    nested = nested_mc.nested_pfe(ps, swaps, eq, cds, n_inner=8, inner_vol=0.0, seed=0)
    closed = exposure.compute_pfe(exposure.portfolio_mtm(swaps, ps, eq, cds), ps.weights)
    assert nested.shape == (ps.horizon,)
    np.testing.assert_allclose(nested, closed, rtol=1e-10, atol=1e-6)


def test_nested_run_reports_revaluation_count(rng):
    ps = _pathset(rng, n_paths=10, horizon=4)
    swaps, eq, cds = bk.load_cross_asset_book(bk.DEFAULT_BOOK_PATH)
    result = nested_mc.run_nested(ps, swaps, eq, cds, n_inner=5, inner_vol=0.01, seed=1)
    assert result.pfe.shape == (4,)
    # 10 outer × 4 dates × 5 inner.
    assert result.n_revaluations == 10 * 4 * 5
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/models/test_nested_mc.py -v
```
Expected: FAIL (`ModuleNotFoundError: chronos2_demo.models.nested_mc`).

- [ ] **Step 3: Implement**

`src/chronos2_demo/models/nested_mc.py`:
```python
"""Nested Monte Carlo exposure engine — BENCHMARK REFERENCE ONLY.

Outer factor scenarios × inner revaluation sub-paths at each exposure date.
This is the cost the FM-path + closed-form pipeline avoids; it is timed against
that pipeline in scripts/benchmark_latency.py. It is deliberately NOT wired into
pricing.exposure.compute_metrics — the demo prices closed-form. See spec §8/§11.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence
import numpy as np
import pandas as pd

from chronos2_demo.types import PathSet
from chronos2_demo.pricing.book import XCCYSwap
from chronos2_demo.pricing.xccy import value_swap_path, DEFAULT_FX_MAP
from chronos2_demo.pricing.instruments import (
    EquityForward, CDSProtection, value_equity_forward_path, value_cds_protection_path,
)
from chronos2_demo.pricing.exposure import compute_pfe


@dataclass(frozen=True)
class NestedResult:
    pfe: np.ndarray          # (horizon,)
    n_revaluations: int


def _reval_one(levels_row: pd.DataFrame, swaps, equity_forwards, cds_protection) -> float:
    """Sum USD MtM of the whole book for a single 1-row levels frame."""
    pv = 0.0
    for s in swaps:
        pv += value_swap_path(s, levels_row, DEFAULT_FX_MAP)[0]
    for f in equity_forwards:
        pv += value_equity_forward_path(f, levels_row, DEFAULT_FX_MAP)[0]
    for c in cds_protection:
        pv += value_cds_protection_path(c, levels_row)[0]
    return pv


def run_nested(
    pathset: PathSet,
    swaps: Sequence[XCCYSwap],
    equity_forwards: Sequence[EquityForward] = (),
    cds_protection: Sequence[CDSProtection] = (),
    n_inner: int = 200,
    inner_vol: float = 0.01,
    q: float = 0.975,
    seed: int = 0,
) -> NestedResult:
    """Nested-MC PFE: at each (outer, t), average book PV over n_inner GBM bumps."""
    rng = np.random.default_rng(seed)
    n_paths, horizon, n_series = pathset.paths.shape
    sim_pv = np.empty((n_paths, horizon))
    n_revals = 0
    for i in range(n_paths):
        for t in range(horizon):
            state = pathset.paths[i, t, :]                       # (n_series,)
            bumps = rng.standard_normal(size=(n_inner, n_series))
            inner_levels = state * np.exp(inner_vol * bumps - 0.5 * inner_vol**2)
            pvs = np.empty(n_inner)
            date_t = pathset.dates[t:t + 1]
            for k in range(n_inner):
                row = pd.DataFrame(inner_levels[k:k + 1], index=date_t,
                                   columns=pathset.series)
                pvs[k] = _reval_one(row, swaps, equity_forwards, cds_protection)
                n_revals += 1
            sim_pv[i, t] = pvs.mean()
    pfe = compute_pfe(sim_pv, pathset.weights, q=q)
    return NestedResult(pfe=pfe, n_revaluations=n_revals)


def nested_pfe(pathset, swaps, equity_forwards=(), cds_protection=(),
               n_inner=200, inner_vol=0.01, q=0.975, seed=0) -> np.ndarray:
    """Convenience: just the PFE curve from run_nested."""
    return run_nested(pathset, swaps, equity_forwards, cds_protection,
                      n_inner=n_inner, inner_vol=inner_vol, q=q, seed=seed).pfe
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/models/test_nested_mc.py -v
```
Expected: PASS (zero-vol nested PFE matches closed form to tolerance).

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/models/nested_mc.py tests/models/test_nested_mc.py
git commit -m "feat(models): nested-MC benchmark exposure engine (reference only)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 37: Latency benchmark script + recorded artifact

**Files:**
- Create: `scripts/benchmark_latency.py`
- Create: `docs/results/latency_benchmark.json` (committed placeholder)
- Test: `tests/test_results_artifacts.py` (create)

A non-test script that times the FM/parametric path-gen + closed-form pricing pipeline against the nested-MC engine on the same `PathSet` + book, and writes the speedup to a committed artifact. Timing belongs to the script (it imports `time` and `perf_counter`); the test only validates artifact *shape* so the suite stays hermetic and fast. The committed artifact starts as a labelled placeholder so the schema check passes before the first real run.

- [ ] **Step 1: Write the failing test**

`tests/test_results_artifacts.py`:
```python
import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[1] / "docs" / "results"


def test_latency_artifact_has_required_shape():
    art = json.loads((RESULTS / "latency_benchmark.json").read_text())
    for key in ("closed_form_seconds", "nested_mc_seconds", "speedup_x",
                "nested_n_revaluations", "status"):
        assert key in art, f"missing {key}"
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/test_results_artifacts.py -v
```
Expected: FAIL (`FileNotFoundError` — `docs/results/latency_benchmark.json` absent).

- [ ] **Step 3: Implement script + placeholder artifact**

Create `docs/results/latency_benchmark.json` (committed placeholder):
```json
{
  "status": "placeholder — run scripts/benchmark_latency.py to populate",
  "closed_form_seconds": null,
  "nested_mc_seconds": null,
  "speedup_x": null,
  "nested_n_revaluations": null,
  "n_paths": null,
  "horizon": null,
  "n_inner": null,
  "git_sha": null,
  "timestamp": null
}
```

Create `scripts/benchmark_latency.py`:
```python
"""Time the FM-path + closed-form pricing pipeline vs the nested-MC strawman.

Writes docs/results/latency_benchmark.json. Non-test, non-hermetic (it times
real computation). See spec §8. Nested MC is a benchmark reference only.

Run: python scripts/benchmark_latency.py [--n-paths 200] [--horizon 12] [--n-inner 200]
"""
from __future__ import annotations
import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from chronos2_demo import config
from chronos2_demo.types import PathSet
from chronos2_demo.pricing import book as bk, exposure
from chronos2_demo.models import nested_mc

OUT = config.REPO_ROOT / "docs" / "results" / "latency_benchmark.json"


def _demo_pathset(n_paths: int, horizon: int) -> PathSet:
    rng = np.random.default_rng(0)
    series = (config.FX_PAIRS
              + [f"{c}_{t}" for c in config.RATES_CCYS for t in config.RATES_TENORS]
              + config.EQUITY_INDICES + config.CREDIT_SPREADS)
    base = np.ones(len(series))
    paths = np.abs(base * (1.0 + rng.normal(0, 0.05, size=(n_paths, horizon, len(series))))) + 0.1
    return PathSet(paths=paths, weights=np.full(n_paths, 1.0 / n_paths),
                   series=series, dates=pd.bdate_range("2022-07-01", periods=horizon),
                   source="parametric")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n-paths", type=int, default=200)
    p.add_argument("--horizon", type=int, default=12)
    p.add_argument("--n-inner", type=int, default=200)
    args = p.parse_args()

    ps = _demo_pathset(args.n_paths, args.horizon)
    swaps, eq, cds = bk.load_cross_asset_book(bk.DEFAULT_BOOK_PATH)

    t0 = time.perf_counter()
    exposure.compute_pfe(exposure.portfolio_mtm(swaps, ps, eq, cds), ps.weights)
    closed_s = time.perf_counter() - t0

    t1 = time.perf_counter()
    res = nested_mc.run_nested(ps, swaps, eq, cds, n_inner=args.n_inner, inner_vol=0.01)
    nested_s = time.perf_counter() - t1

    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    artifact = {
        "status": "measured",
        "closed_form_seconds": round(closed_s, 4),
        "nested_mc_seconds": round(nested_s, 4),
        "speedup_x": round(nested_s / closed_s, 1) if closed_s > 0 else None,
        "nested_n_revaluations": res.n_revaluations,
        "n_paths": args.n_paths,
        "horizon": args.horizon,
        "n_inner": args.n_inner,
        "git_sha": sha,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    OUT.write_text(json.dumps(artifact, indent=2) + "\n")
    print(json.dumps(artifact, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/test_results_artifacts.py::test_latency_artifact_has_required_shape -v
```
Expected: PASS (placeholder satisfies the shape check).

Optional local sanity (not part of the hermetic suite): `python scripts/benchmark_latency.py --n-paths 50 --horizon 6 --n-inner 50` then re-run the test.

- [ ] **Step 5: Commit**

```bash
git add scripts/benchmark_latency.py docs/results/latency_benchmark.json tests/test_results_artifacts.py
git commit -m "feat(scripts): nested-MC-vs-FM latency benchmark + recorded artifact

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Stage 12 — Live headline calibration

The genuine PFE delta from the real Chronos-2 endpoint, recorded to a committed artifact. The script is non-test and deploy-gated (it imports `infra.sagemaker_endpoint.open_endpoint`, the single AutoGluon import point). The hermetic suite only checks the artifact's shape.

### Task 38: Live calibration script + recorded artifact

**Files:**
- Create: `scripts/calibrate_headline.py`
- Create: `docs/results/headline_calibration.json` (committed placeholder)
- Test: `tests/test_results_artifacts.py` (modify — add the headline shape check)

The script runs the full real pipeline once (baseline + real-endpoint chronos2 + blend + cross-asset pricing) on the curated snapshot in a chosen stress window and records the measured baseline/augmented PFE, `delta_pct`, `delta_usd`, and full provenance. It reuses `simulate_chronos2` exactly as the Fargate task does.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_results_artifacts.py`:
```python
def test_headline_artifact_has_required_shape():
    art = json.loads((RESULTS / "headline_calibration.json").read_text())
    for key in ("status", "baseline_pfe_975", "augmented_pfe_975",
                "delta_pct", "delta_usd", "as_of", "stress_window",
                "n_paths", "endpoint_name", "git_sha", "timestamp"):
        assert key in art, f"missing {key}"
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/test_results_artifacts.py::test_headline_artifact_has_required_shape -v
```
Expected: FAIL (`FileNotFoundError`).

- [ ] **Step 3: Implement script + placeholder artifact**

Create `docs/results/headline_calibration.json` (committed placeholder):
```json
{
  "status": "placeholder — run scripts/calibrate_headline.py against a live endpoint",
  "baseline_pfe_975": null,
  "augmented_pfe_975": null,
  "delta_pct": null,
  "delta_usd": null,
  "as_of": null,
  "stress_window": null,
  "n_paths": null,
  "endpoint_name": null,
  "git_sha": null,
  "timestamp": null
}
```

Create `scripts/calibrate_headline.py`:
```python
"""Measure the GENUINE headline PFE delta against the real Chronos-2 endpoint.

Writes docs/results/headline_calibration.json. Non-test, deploy-gated: needs a
live AutoGluon endpoint and the curated snapshot (scripts/snapshot_data.py).
The hermetic test suite never runs this; tests/test_headline_numbers.py remains
the offline plumbing guard. See spec §8.

Run: python scripts/calibrate_headline.py --endpoint-name chronos2-demo-ep \
        --as-of 2022-09-30 --stress-window 2022_rate_hike
"""
from __future__ import annotations
import argparse
import json
import subprocess
from datetime import datetime, timezone

import pandas as pd

from chronos2_demo import config
from chronos2_demo.augmentation import blender, regime_detector
from chronos2_demo.models import baseline_mc, chronos2_client
from chronos2_demo.infra import sagemaker_endpoint
from chronos2_demo.pricing import book as bk, exposure

OUT = config.REPO_ROOT / "docs" / "results" / "headline_calibration.json"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--endpoint-name", required=True)
    p.add_argument("--as-of", required=True)
    p.add_argument("--stress-window", required=True)
    p.add_argument("--horizon", type=int, default=config.DEFAULT_HORIZON_DAYS)
    p.add_argument("--n-paths", type=int, default=config.DEFAULT_N_PATHS)
    args = p.parse_args()

    panel = pd.read_parquet(config.DATA_CURATED / "panel.parquet")
    covariates = pd.read_parquet(config.DATA_CURATED / "covariates.parquet")
    swaps, eq, cds = bk.load_cross_asset_book(bk.DEFAULT_BOOK_PATH)

    snap = regime_detector.current_w_stress(panel, as_of=args.as_of, window=20)
    par = baseline_mc.simulate_baseline(
        panel, as_of=args.as_of, horizon=args.horizon, n_paths=args.n_paths,
        n_components=5, seed=0)

    endpoint = sagemaker_endpoint.open_endpoint(args.endpoint_name)
    client = chronos2_client.Chronos2Client(endpoint=endpoint)
    # simulate_chronos2 slices covariates to the lookback window internally, so
    # pass the full frame — it aligns cov to the sliced history index for us.
    chr_ = chronos2_client.simulate_chronos2(
        client, panel, as_of=args.as_of, horizon=args.horizon, n_paths=args.n_paths,
        covariates=covariates, lookback_days=config.DEFAULT_LOOKBACK_DAYS)

    par_term = exposure.portfolio_mtm(swaps, par, eq, cds)[:, -1]
    chr_term = exposure.portfolio_mtm(swaps, chr_, eq, cds)[:, -1]
    blended = blender.blend_paths(par, chr_, par_term, chr_term, w_stress=snap.w_stress)

    base_pfe = float(exposure.compute_metrics(
        swaps, par, equity_forwards=eq, cds_protection=cds)["pfe_975"][-1])
    aug_pfe = float(exposure.compute_metrics(
        swaps, blended, equity_forwards=eq, cds_protection=cds)["pfe_975"][-1])
    delta_usd = aug_pfe - base_pfe
    delta_pct = delta_usd / base_pfe * 100.0 if base_pfe else None

    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    artifact = {
        "status": "measured",
        "baseline_pfe_975": round(base_pfe, 2),
        "augmented_pfe_975": round(aug_pfe, 2),
        "delta_pct": round(delta_pct, 2) if delta_pct is not None else None,
        "delta_usd": round(delta_usd, 2),
        "as_of": args.as_of,
        "stress_window": args.stress_window,
        "w_stress": round(float(snap.w_stress), 4),
        "n_paths": args.n_paths,
        "endpoint_name": args.endpoint_name,
        "git_sha": sha,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    OUT.write_text(json.dumps(artifact, indent=2) + "\n")
    print(json.dumps(artifact, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/test_results_artifacts.py -v
```
Expected: PASS (both artifact shape checks green).

- [ ] **Step 5: Commit**

```bash
git add scripts/calibrate_headline.py docs/results/headline_calibration.json tests/test_results_artifacts.py
git commit -m "feat(scripts): live-endpoint headline calibration + recorded artifact

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 39: Snapshot the cross-asset columns + README/runbook note

**Files:**
- Modify: `scripts/snapshot_data.py`
- Modify: `README.md`
- Test: `tests/test_notebook_smoke.py` (verify still green; no new test)

The snapshot must pull SPX/NIKKEI225/US_IG_OAS/US_HY_OAS into `panel.parquet` so the live scripts and notebook see the full universe. Equity uses the existing FRED fetcher; credit uses Task 31's `fetch_credit_oas`.

- [ ] **Step 1: Extend the snapshot script**

In `scripts/snapshot_data.py`, after the rates loop (before `panel = align_panel(series)`), append:
```python
    for idx in config.EQUITY_INDICES:
        fred_id = {"SPX": "SP500", "NIKKEI225": "NIKKEI225"}[idx]
        series.append(fetch.fetch_fred_series(fred_id, args.fred_api_key).rename(idx))

    for name in config.CREDIT_SPREADS:
        series.append(fetch.fetch_credit_oas(name, args.fred_api_key))
```

- [ ] **Step 2: Note the wider universe in the README**

In `README.md`, under "Snapshot the data", replace the panel description line:
```markdown
This produces `data/curated/panel.parquet` (FX + G10 rates + equity SPX/NIKKEI225
+ credit US_IG/US_HY OAS — the full cross-asset factor universe) and
`data/curated/covariates.parquet` (VIX/MOVE/WTI, Chronos-2-only).
```
And add a line under "Run the headline notebook":
```markdown
The genuine headline delta is recorded by `python scripts/calibrate_headline.py`
(live endpoint) into `docs/results/headline_calibration.json`; the nested-MC-vs-FM
speedup by `python scripts/benchmark_latency.py` into
`docs/results/latency_benchmark.json`.
```

- [ ] **Step 3: Run the hermetic suite**

```bash
pytest -q
```
Expected: PASS — full suite (the smoke test mocks fetchers, so the snapshot change doesn't touch it; SP500/NIKKEI225 fetch is only exercised live).

- [ ] **Step 4: Commit**

```bash
git add scripts/snapshot_data.py README.md
git commit -m "feat(scripts): snapshot equity + credit columns; document calibration artifacts

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Plan A part-4 complete

After Task 39:
- The factor universe is rates + FX + equity + credit (~21 series), priced by a cross-asset book (XCCY + equity forward + CDS proxy).
- A nested-MC strawman exists as a benchmark reference, correctness-pinned, never on the demo pricing path.
- Two committed artifacts record the genuine real-endpoint headline delta and the nested-MC-vs-FM speedup once their scripts are run.

> _Continue with `2026-05-22-plan-a-quant-pipeline-part-5.md` (Stage 13 — all-live market data sources + S3 seeding; added 2026-06-05)._
