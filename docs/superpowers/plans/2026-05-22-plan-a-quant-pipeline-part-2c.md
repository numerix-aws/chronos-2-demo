# Plan A — Part 2c: Stage 4 — Augmentation (Regime + Blender)

> **Continuation of** `2026-05-22-plan-a-quant-pipeline-part-2b.md`. Tasks 15–17.

---

## Stage 4 — Augmentation: regime detector + blender

This stage implements the **most-scrutinized component** of the demo. It must be auditable: every input → output relationship is a deterministic function the demo can display.

The augmentation layer takes two `PathSet`s (parametric and Chronos-2) and a snapshot of regime features at the as-of date, and produces a single blended `PathSet` whose source is `"blended"`. Per the spec:

- `w_stress ∈ [0,1]` keys both engines: parametric weight = `(1 - w_stress)`, Chronos-2 weight = `w_stress` in the tail bucket.
- In the body, parametric weight = 0.9, Chronos-2 contribution = 0.1 — augmentation is visible even in calm regimes.
- "Tail" = paths with terminal portfolio P&L in the top/bottom 5%. Since the augmentation layer doesn't yet know the portfolio, it accepts a per-path "tail score" callable from the caller; pricing supplies it.
- Importance weighting only — no path deletion.

### Task 15: `RegimeSnapshot` + `current_w_stress`

**Files:**
- Create: `src/chronos2_demo/augmentation/__init__.py`
- Create: `src/chronos2_demo/augmentation/regime_detector.py`
- Create: `tests/augmentation/__init__.py`
- Create: `tests/augmentation/test_regime_detector.py`

- [ ] **Step 1: Write the failing tests**

`tests/augmentation/__init__.py`: empty.

`tests/augmentation/test_regime_detector.py`:
```python
import numpy as np
import pandas as pd
import pytest
from chronos2_demo.augmentation import regime_detector as rd


def _flat_panel(n=300):
    idx = pd.bdate_range("2020-01-02", periods=n)
    cols = ["USDEUR", "USDJPY", "USD_2Y", "USD_5Y", "USD_10Y"]
    return pd.DataFrame(np.ones((n, 5)) + 1e-3, index=idx, columns=cols)


def _shocked_panel(n=300, shock_start=200, shock_len=30):
    panel = _flat_panel(n)
    rng = np.random.default_rng(0)
    panel.iloc[shock_start:shock_start + shock_len] += rng.normal(0, 0.1,
                                                                  size=(shock_len, 5))
    return panel


def test_current_w_stress_is_unit_interval_value():
    panel = _shocked_panel()
    snap = rd.current_w_stress(panel, as_of=panel.index[-1].strftime("%Y-%m-%d"),
                               window=20)
    assert isinstance(snap, rd.RegimeSnapshot)
    assert 0.0 <= snap.w_stress <= 1.0
    assert {"rolling_vol", "rates_fx_corr", "vol_of_vol"} <= set(snap.features)


def test_current_w_stress_is_high_in_shock_period():
    panel = _shocked_panel(shock_start=200, shock_len=30)
    in_shock_date = panel.index[225].strftime("%Y-%m-%d")
    calm_date = panel.index[100].strftime("%Y-%m-%d")
    w_shock = rd.current_w_stress(panel, in_shock_date, window=20).w_stress
    w_calm = rd.current_w_stress(panel, calm_date, window=20).w_stress
    assert w_shock > w_calm + 0.2


def test_current_w_stress_rejects_unknown_as_of():
    panel = _flat_panel()
    with pytest.raises(KeyError):
        rd.current_w_stress(panel, "2099-01-01", window=20)
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/augmentation/test_regime_detector.py -v
```

- [ ] **Step 3: Implement files**

`src/chronos2_demo/augmentation/__init__.py`: empty.

`src/chronos2_demo/augmentation/regime_detector.py`:
```python
"""Pointwise regime snapshot used by the blender at a single as-of date.

This is a thin adapter over data/regimes.py: it computes the rolling features
on the full panel, then returns the value AT the given as-of date along with
the displayable feature dict.
"""
from __future__ import annotations
from dataclasses import dataclass
import pandas as pd

from chronos2_demo.data.regimes import regime_features, w_stress_series


@dataclass(frozen=True)
class RegimeSnapshot:
    as_of: pd.Timestamp
    w_stress: float
    features: dict[str, float]


def current_w_stress(panel: pd.DataFrame, as_of: str, window: int = 20) -> RegimeSnapshot:
    as_of_ts = pd.Timestamp(as_of)
    feats = regime_features(panel, window=window)
    if as_of_ts not in feats.index:
        raise KeyError(f"as_of {as_of} not in computed feature index")
    w = w_stress_series(panel, window=window)
    return RegimeSnapshot(
        as_of=as_of_ts,
        w_stress=float(w.loc[as_of_ts]),
        features={k: float(v) for k, v in feats.loc[as_of_ts].items()},
    )
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/augmentation/test_regime_detector.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/augmentation/__init__.py \
        src/chronos2_demo/augmentation/regime_detector.py \
        tests/augmentation/__init__.py tests/augmentation/test_regime_detector.py
git commit -m "feat(augmentation): regime snapshot at a single as-of date

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 16: Tail-bucket + body weight calculator

**Files:**
- Create: `src/chronos2_demo/augmentation/blender.py` (this task adds only weight math)
- Create: `tests/augmentation/test_blender_weights.py`

The blender owns one important pure function — given two `PathSet`s, a per-path "tail score" array, and `w_stress`, produce a final weight vector for each engine. We implement and test this in isolation before plumbing it into `blend_paths`.

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np
import pytest
from chronos2_demo.augmentation import blender as bl


def test_compute_weights_uniform_when_w_stress_zero():
    n = 1000
    pnl = np.random.default_rng(0).normal(size=n)
    w_par, w_chr = bl.compute_weights(pnl_parametric=pnl, pnl_chronos2=pnl,
                                      w_stress=0.0, body_chronos_share=0.1,
                                      tail_quantile=0.05)
    # In calm regimes: parametric ~ 0.9 in body and ~1.0 in tail; Chronos2 mirrors.
    assert np.isclose(w_par.sum() + w_chr.sum(), 2.0)  # one per engine
    assert (w_par > 0).all() and (w_chr >= 0).all()


def test_compute_weights_tail_swings_toward_chronos2_in_stress():
    rng = np.random.default_rng(0)
    n = 4000
    pnl = rng.normal(size=n)
    w_par_calm, w_chr_calm = bl.compute_weights(pnl, pnl, w_stress=0.0,
                                                body_chronos_share=0.1,
                                                tail_quantile=0.05)
    w_par_stress, w_chr_stress = bl.compute_weights(pnl, pnl, w_stress=1.0,
                                                    body_chronos_share=0.1,
                                                    tail_quantile=0.05)
    tail_mask = (pnl <= np.quantile(pnl, 0.05)) | (pnl >= np.quantile(pnl, 0.95))
    # Stress -> chronos2 weight in tail dominates parametric in tail.
    assert w_chr_stress[tail_mask].sum() > w_par_stress[tail_mask].sum() * 5
    # Calm -> opposite.
    assert w_par_calm[tail_mask].sum() > w_chr_calm[tail_mask].sum() * 5


def test_compute_weights_each_set_sums_to_one():
    rng = np.random.default_rng(0)
    pnl_par = rng.normal(size=2000)
    pnl_chr = rng.normal(size=2000)
    for w_stress in (0.0, 0.3, 0.7, 1.0):
        w_par, w_chr = bl.compute_weights(pnl_par, pnl_chr, w_stress=w_stress,
                                          body_chronos_share=0.1,
                                          tail_quantile=0.05)
        assert np.isclose(w_par.sum(), 1.0)
        assert np.isclose(w_chr.sum(), 1.0)


def test_compute_weights_rejects_invalid_inputs():
    pnl = np.zeros(10)
    with pytest.raises(ValueError):
        bl.compute_weights(pnl, pnl, w_stress=1.5,
                           body_chronos_share=0.1, tail_quantile=0.05)
    with pytest.raises(ValueError):
        bl.compute_weights(pnl, pnl, w_stress=0.5,
                           body_chronos_share=-0.1, tail_quantile=0.05)
    with pytest.raises(ValueError):
        bl.compute_weights(pnl, pnl, w_stress=0.5,
                           body_chronos_share=0.1, tail_quantile=0.6)
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/augmentation/test_blender_weights.py -v
```

- [ ] **Step 3: Implement `src/chronos2_demo/augmentation/blender.py` (weights only)**

```python
"""Blend two PathSets via deterministic, displayable weight rules.

This file is split across Tasks 16-17. Task 16 adds compute_weights;
Task 17 adds blend_paths that calls it and emits a final PathSet.
"""
from __future__ import annotations
import numpy as np


def _validate(w_stress: float, body_chronos_share: float, tail_quantile: float) -> None:
    if not 0.0 <= w_stress <= 1.0:
        raise ValueError(f"w_stress must be in [0,1], got {w_stress}")
    if not 0.0 <= body_chronos_share <= 1.0:
        raise ValueError(f"body_chronos_share must be in [0,1], got {body_chronos_share}")
    if not 0.0 < tail_quantile < 0.5:
        raise ValueError(f"tail_quantile must be in (0, 0.5), got {tail_quantile}")


def compute_weights(
    pnl_parametric: np.ndarray,
    pnl_chronos2: np.ndarray,
    w_stress: float,
    body_chronos_share: float = 0.1,
    tail_quantile: float = 0.05,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (w_parametric, w_chronos2), each summing to 1.

    Rules:
      For each engine independently:
        - Mark the union (top tail_quantile, bottom tail_quantile) within that engine's PnL as "tail".
        - In the tail bucket: weight ∝ (1 - w_stress) for parametric, w_stress for chronos2.
        - In the body bucket: weight ∝ (1 - body_chronos_share) for parametric,
          body_chronos_share for chronos2.
      Then renormalize each engine's vector to sum to 1.
    """
    _validate(w_stress, body_chronos_share, tail_quantile)

    def _engine_weights(pnl: np.ndarray, tail_share: float, body_share: float) -> np.ndarray:
        lo = np.quantile(pnl, tail_quantile)
        hi = np.quantile(pnl, 1 - tail_quantile)
        tail_mask = (pnl <= lo) | (pnl >= hi)
        body_mask = ~tail_mask
        n_tail = tail_mask.sum()
        n_body = body_mask.sum()
        # If a bucket is empty, fall back to uniform within the other.
        if n_tail == 0:
            return np.ones_like(pnl) / pnl.size
        if n_body == 0:
            return np.ones_like(pnl) / pnl.size
        per_tail = tail_share / n_tail
        per_body = body_share / n_body
        w = np.where(tail_mask, per_tail, per_body)
        # Normalize defensively; tail_share + body_share need not equal 1 a priori.
        return w / w.sum()

    w_par = _engine_weights(pnl_parametric, tail_share=(1 - w_stress),
                            body_share=(1 - body_chronos_share))
    w_chr = _engine_weights(pnl_chronos2, tail_share=w_stress,
                            body_share=body_chronos_share)
    return w_par, w_chr
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/augmentation/test_blender_weights.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/augmentation/blender.py tests/augmentation/test_blender_weights.py
git commit -m "feat(augmentation): tail vs body weight rules

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 17: `blend_paths` — combine two PathSets into one weighted PathSet

**Files:**
- Modify: `src/chronos2_demo/augmentation/blender.py` (append `blend_paths`)
- Create: `tests/augmentation/test_blender_blend.py`

Pricing (Stage 5) needs the blended set in a form it can pass to its existing `(paths, weights)` interface. Rather than emit two engines and a master weight, we emit a **single PathSet of size `n_par + n_chr`** with the two stacked along the path axis and weights normalized so that the total is 1. Pricing then sums weighted exposures with no awareness of which engine each path came from.

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np
import pandas as pd
from chronos2_demo.augmentation import blender as bl
from chronos2_demo.types import PathSet


def _ps(n_paths, source, fill, horizon=10, n_series=3):
    paths = np.full((n_paths, horizon, n_series), fill, dtype=float)
    weights = np.full(n_paths, 1.0 / n_paths)
    return PathSet(
        paths=paths,
        weights=weights,
        series=["A", "B", "C"],
        dates=pd.bdate_range("2022-07-01", periods=horizon),
        source=source,
    )


def test_blend_paths_concatenates_paths_and_normalizes_weights():
    par = _ps(100, "parametric", fill=1.0)
    chr_ = _ps(80, "chronos2", fill=2.0)
    pnl_par = np.random.default_rng(0).normal(size=100)
    pnl_chr = np.random.default_rng(1).normal(size=80)
    out = bl.blend_paths(par, chr_, pnl_par, pnl_chr, w_stress=0.7)
    assert out.source == "blended"
    assert out.paths.shape == (180, 10, 3)
    # First 100 paths come from parametric (filled with 1.0); next 80 from chronos2 (2.0).
    assert (out.paths[:100] == 1.0).all()
    assert (out.paths[100:] == 2.0).all()
    assert np.isclose(out.weights.sum(), 1.0)


def test_blend_paths_preserves_dates_and_series_from_first_pathset():
    par = _ps(10, "parametric", fill=1.0)
    chr_ = _ps(10, "chronos2", fill=1.0)
    pnl = np.zeros(10)
    out = bl.blend_paths(par, chr_, pnl, pnl, w_stress=0.3)
    assert list(out.series) == par.series
    assert list(out.dates) == list(par.dates)
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/augmentation/test_blender_blend.py -v
```

- [ ] **Step 3: Append to `src/chronos2_demo/augmentation/blender.py`**

```python
import pandas as pd
from chronos2_demo.types import PathSet


def blend_paths(
    parametric: PathSet,
    chronos2: PathSet,
    pnl_parametric: np.ndarray,
    pnl_chronos2: np.ndarray,
    w_stress: float,
    body_chronos_share: float = 0.1,
    tail_quantile: float = 0.05,
) -> PathSet:
    """Stack the two PathSets along the path axis and emit normalized weights.

    Returned weights sum to 1 across all (n_par + n_chr) paths, so the result
    can be passed straight into `pricing.exposure.compute_pfe(...)` as if it
    were a single engine's output.
    """
    if parametric.series != chronos2.series:
        raise ValueError("series ordering must match across PathSets")
    if not parametric.dates.equals(chronos2.dates):
        raise ValueError("dates must match across PathSets")
    if parametric.paths.shape[1:] != chronos2.paths.shape[1:]:
        raise ValueError("horizon / n_series must match")

    w_par, w_chr = compute_weights(
        pnl_parametric, pnl_chronos2,
        w_stress=w_stress,
        body_chronos_share=body_chronos_share,
        tail_quantile=tail_quantile,
    )
    # Each engine's weights sum to 1; combine 50/50 across engines so the
    # union sums to 1 with each engine's relative weighting preserved.
    combined = np.concatenate([0.5 * w_par, 0.5 * w_chr])
    paths = np.concatenate([parametric.paths, chronos2.paths], axis=0)
    return PathSet(
        paths=paths,
        weights=combined,
        series=list(parametric.series),
        dates=parametric.dates,
        source="blended",
    )
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/augmentation/test_blender_blend.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/augmentation/blender.py tests/augmentation/test_blender_blend.py
git commit -m "feat(augmentation): blend_paths concatenates engines with normalized weights

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

> _Continue with `2026-05-22-plan-a-quant-pipeline-part-2d.md` (Stage 5 — Pricing & exposure, Tasks 18–21)._
