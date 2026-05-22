# Plan A — Part 3a: Stage 6 — Diagnostics

> **Continuation of** `2026-05-22-plan-a-quant-pipeline-part-2d.md`. Tasks 22–24.

---

## Stage 6 — Diagnostics

The diagnostics layer answers the audience question: *"Is the augmentation actually doing something defensible?"* Three orthogonal checks the demo can render side-by-side:

- **Coverage** — regime-conditional band coverage (does an X% prediction interval cover X% of realized history in calm vs stress?).
- **Tail dependence** — exceedance correlation between FX and rates conditional on a tail bucket (does the joint move with the right shape?).
- **Distribution** — KS and energy-distance comparisons of marginal forecast distributions vs realized.

All three operate on a `PathSet` plus a realized `pd.DataFrame` history aligned to the same horizon dates. They return small numeric summaries — not plots — so the headline notebook can either render them directly or feed them into the plotting layer (Stage 7).

### Task 22: Regime-conditional band coverage

**Files:**
- Create: `src/chronos2_demo/diagnostics/__init__.py`
- Create: `src/chronos2_demo/diagnostics/coverage.py`
- Create: `tests/diagnostics/__init__.py`
- Create: `tests/diagnostics/test_coverage.py`

The coverage check picks a quantile pair (e.g., 5/95) per series per timestep from the `PathSet` and asks: across all timesteps **labeled stress**, does the realized series fall inside the band 90% of the time? Then the same for calm. Big gap = the engine misjudges the regime it claims to be modeling.

- [ ] **Step 1: Write the failing tests**

`tests/diagnostics/__init__.py`: empty.

`tests/diagnostics/test_coverage.py`:
```python
import numpy as np
import pandas as pd
import pytest
from chronos2_demo.diagnostics import coverage as cov
from chronos2_demo.types import PathSet


def _pathset(paths, weights=None, series=None, dates=None):
    n_paths, horizon, n_series = paths.shape
    weights = weights if weights is not None else np.full(n_paths, 1.0 / n_paths)
    series = series or [f"S{i}" for i in range(n_series)]
    dates = dates if dates is not None else pd.bdate_range("2022-07-01", periods=horizon)
    return PathSet(paths=paths, weights=weights, series=series, dates=dates,
                   source="parametric")


def test_band_coverage_perfect_when_all_realized_inside_band():
    rng = np.random.default_rng(0)
    n_paths, horizon, n_series = 1000, 30, 2
    paths = rng.normal(0, 1, size=(n_paths, horizon, n_series))
    ps = _pathset(paths)
    realized = pd.DataFrame(np.zeros((horizon, n_series)),
                            index=ps.dates, columns=ps.series)
    rate = cov.band_coverage(ps, realized, q_low=0.05, q_high=0.95)
    # Realized identically zero is well inside a (-1.64, 1.64) band on every series.
    assert (rate > 0.9).all()


def test_band_coverage_drops_when_realized_outside_band():
    rng = np.random.default_rng(0)
    n_paths, horizon, n_series = 1000, 30, 2
    paths = rng.normal(0, 1, size=(n_paths, horizon, n_series))
    ps = _pathset(paths)
    realized = pd.DataFrame(np.full((horizon, n_series), 5.0),
                            index=ps.dates, columns=ps.series)
    rate = cov.band_coverage(ps, realized, q_low=0.05, q_high=0.95)
    assert (rate < 0.1).all()


def test_regime_conditional_coverage_splits_by_w_stress():
    rng = np.random.default_rng(0)
    n_paths, horizon, n_series = 800, 20, 1
    paths = rng.normal(0, 1, size=(n_paths, horizon, n_series))
    ps = _pathset(paths)
    realized = pd.DataFrame(np.zeros((horizon, n_series)),
                            index=ps.dates, columns=ps.series)
    # First 10 timesteps calm, next 10 stress.
    w_stress = pd.Series(
        [0.1] * 10 + [0.9] * 10, index=ps.dates, name="w_stress"
    )
    out = cov.regime_conditional_coverage(ps, realized, w_stress,
                                          q_low=0.05, q_high=0.95,
                                          stress_threshold=0.7)
    assert set(out.keys()) == {"calm", "stress"}
    assert "S0" in out["calm"].index
    assert "S0" in out["stress"].index


def test_band_coverage_rejects_misaligned_realized():
    rng = np.random.default_rng(0)
    paths = rng.normal(0, 1, size=(50, 10, 2))
    ps = _pathset(paths)
    bad = pd.DataFrame(np.zeros((9, 2)),
                       index=pd.bdate_range("2022-07-01", periods=9),
                       columns=ps.series)
    with pytest.raises(ValueError, match="align"):
        cov.band_coverage(ps, bad, q_low=0.05, q_high=0.95)
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/diagnostics/test_coverage.py -v
```

- [ ] **Step 3: Implement files**

`src/chronos2_demo/diagnostics/__init__.py`: empty.

`src/chronos2_demo/diagnostics/coverage.py`:
```python
"""Regime-conditional band coverage diagnostic.

Given a PathSet and aligned realized series, compute the fraction of timesteps
at which the realized value falls inside the [q_low, q_high] weighted-quantile
band of the path samples — overall and split by an external w_stress series.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from chronos2_demo.types import PathSet


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    order = np.argsort(values)
    v = values[order]
    w = weights[order]
    cw = np.cumsum(w)
    cw /= cw[-1]
    return float(np.interp(q, cw, v))


def _band_per_series_per_t(
    pathset: PathSet, q_low: float, q_high: float
) -> tuple[np.ndarray, np.ndarray]:
    """Return (lo, hi) bands shaped (horizon, n_series)."""
    horizon, n_series = pathset.horizon, pathset.n_series
    lo = np.empty((horizon, n_series))
    hi = np.empty((horizon, n_series))
    for t in range(horizon):
        for j in range(n_series):
            v = pathset.paths[:, t, j]
            lo[t, j] = _weighted_quantile(v, pathset.weights, q_low)
            hi[t, j] = _weighted_quantile(v, pathset.weights, q_high)
    return lo, hi


def band_coverage(
    pathset: PathSet,
    realized: pd.DataFrame,
    q_low: float = 0.05,
    q_high: float = 0.95,
) -> pd.Series:
    """Per-series fraction of timesteps with realized inside the [q_low, q_high] band."""
    if not realized.index.equals(pathset.dates):
        raise ValueError("realized index must align with pathset.dates")
    if list(realized.columns) != pathset.series:
        raise ValueError("realized columns must match pathset.series")
    lo, hi = _band_per_series_per_t(pathset, q_low, q_high)
    rv = realized.values
    inside = (rv >= lo) & (rv <= hi)
    rates = inside.mean(axis=0)
    return pd.Series(rates, index=pathset.series, name="band_coverage")


def regime_conditional_coverage(
    pathset: PathSet,
    realized: pd.DataFrame,
    w_stress: pd.Series,
    q_low: float = 0.05,
    q_high: float = 0.95,
    stress_threshold: float = 0.7,
) -> dict[str, pd.Series]:
    """Split coverage by w_stress regime and return {'calm': ..., 'stress': ...}."""
    if not realized.index.equals(pathset.dates):
        raise ValueError("realized index must align with pathset.dates")
    if not w_stress.index.equals(pathset.dates):
        raise ValueError("w_stress index must align with pathset.dates")
    lo, hi = _band_per_series_per_t(pathset, q_low, q_high)
    rv = realized.values
    inside = (rv >= lo) & (rv <= hi)  # (horizon, n_series)
    stress_mask = (w_stress.values >= stress_threshold)
    calm_mask = ~stress_mask

    def _frac(mask: np.ndarray) -> pd.Series:
        if not mask.any():
            return pd.Series(np.full(pathset.n_series, np.nan), index=pathset.series)
        return pd.Series(inside[mask].mean(axis=0), index=pathset.series)

    return {"calm": _frac(calm_mask), "stress": _frac(stress_mask)}
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/diagnostics/test_coverage.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/diagnostics/__init__.py \
        src/chronos2_demo/diagnostics/coverage.py \
        tests/diagnostics/__init__.py tests/diagnostics/test_coverage.py
git commit -m "feat(diagnostics): regime-conditional band coverage

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 23: Tail dependence — exceedance correlation

**Files:**
- Create: `src/chronos2_demo/diagnostics/tail_dependence.py`
- Create: `tests/diagnostics/test_tail_dependence.py`

**What it measures:** for a pair of series, the correlation of their joint moves *conditional on both being in the tail*. Parametric Gaussian-driven engines famously underestimate this — exceedance correlation under stress is higher than the unconditional correlation suggests. The diagnostic compares the path-set tail correlation to the realized history tail correlation; a closer match is a better engine.

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np
import pandas as pd
import pytest
from chronos2_demo.diagnostics import tail_dependence as td
from chronos2_demo.types import PathSet


def _pathset_from_log_rets(log_rets: np.ndarray, series: list[str]) -> PathSet:
    """Cumulate log returns into levels, build a PathSet."""
    levels = np.exp(log_rets.cumsum(axis=1))
    n_paths, horizon, _ = levels.shape
    return PathSet(
        paths=levels,
        weights=np.full(n_paths, 1.0 / n_paths),
        series=series,
        dates=pd.bdate_range("2022-07-01", periods=horizon),
        source="parametric",
    )


def test_exceedance_corr_high_when_pair_co_moves_in_tail():
    rng = np.random.default_rng(0)
    n_paths, horizon = 4000, 20
    common = rng.normal(0, 0.02, size=(n_paths, horizon, 1))
    a = common + rng.normal(0, 0.005, size=(n_paths, horizon, 1))
    b = common + rng.normal(0, 0.005, size=(n_paths, horizon, 1))
    log_rets = np.concatenate([a, b], axis=2)
    ps = _pathset_from_log_rets(log_rets, ["A", "B"])
    val = td.exceedance_correlation(ps, "A", "B", quantile=0.05)
    assert val > 0.5


def test_exceedance_corr_low_for_independent_pair():
    rng = np.random.default_rng(0)
    n_paths, horizon = 4000, 20
    a = rng.normal(0, 0.02, size=(n_paths, horizon, 1))
    b = rng.normal(0, 0.02, size=(n_paths, horizon, 1))
    log_rets = np.concatenate([a, b], axis=2)
    ps = _pathset_from_log_rets(log_rets, ["A", "B"])
    val = td.exceedance_correlation(ps, "A", "B", quantile=0.05)
    assert -0.2 < val < 0.2


def test_exceedance_corr_realized_matches_when_drawn_from_same_dgp():
    rng = np.random.default_rng(0)
    n_obs = 2000
    common = rng.normal(0, 0.02, size=n_obs)
    a = common + rng.normal(0, 0.005, size=n_obs)
    b = common + rng.normal(0, 0.005, size=n_obs)
    realized = pd.DataFrame({"A": np.exp(np.cumsum(a)), "B": np.exp(np.cumsum(b))},
                            index=pd.bdate_range("2018-01-02", periods=n_obs))
    val = td.realized_exceedance_correlation(realized, "A", "B", quantile=0.05)
    assert val > 0.4


def test_exceedance_corr_rejects_unknown_series():
    rng = np.random.default_rng(0)
    log_rets = rng.normal(0, 0.01, size=(100, 5, 2))
    ps = _pathset_from_log_rets(log_rets, ["A", "B"])
    with pytest.raises(KeyError):
        td.exceedance_correlation(ps, "A", "Z", quantile=0.05)
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/diagnostics/test_tail_dependence.py -v
```

- [ ] **Step 3: Implement `src/chronos2_demo/diagnostics/tail_dependence.py`**

```python
"""Exceedance correlation: Pearson correlation of log-return pairs
conditional on both being below a low quantile or both above a high quantile.

Definition used here:
  joint_tail = (a < q_low(a)) & (b < q_low(b))
            | (a > q_high(a)) & (b > q_high(b))
  return corrcoef(a[joint_tail], b[joint_tail])

This captures the "they crash together" effect that Gaussian copulas miss.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from chronos2_demo.types import PathSet


def _series_index(pathset: PathSet, name: str) -> int:
    if name not in pathset.series:
        raise KeyError(f"series {name!r} not in pathset.series={pathset.series}")
    return pathset.series.index(name)


def _path_log_returns_flat(pathset: PathSet, name: str) -> np.ndarray:
    j = _series_index(pathset, name)
    levels = pathset.paths[:, :, j]  # (n_paths, horizon)
    log_rets = np.diff(np.log(levels), axis=1)  # (n_paths, horizon-1)
    return log_rets.flatten()


def exceedance_correlation(
    pathset: PathSet,
    series_a: str,
    series_b: str,
    quantile: float = 0.05,
) -> float:
    a = _path_log_returns_flat(pathset, series_a)
    b = _path_log_returns_flat(pathset, series_b)
    return _exceedance_corr(a, b, quantile)


def realized_exceedance_correlation(
    realized: pd.DataFrame,
    series_a: str,
    series_b: str,
    quantile: float = 0.05,
) -> float:
    a = np.diff(np.log(realized[series_a].values))
    b = np.diff(np.log(realized[series_b].values))
    return _exceedance_corr(a, b, quantile)


def _exceedance_corr(a: np.ndarray, b: np.ndarray, quantile: float) -> float:
    qa_lo, qa_hi = np.quantile(a, [quantile, 1 - quantile])
    qb_lo, qb_hi = np.quantile(b, [quantile, 1 - quantile])
    joint_low = (a < qa_lo) & (b < qb_lo)
    joint_high = (a > qa_hi) & (b > qb_hi)
    mask = joint_low | joint_high
    if mask.sum() < 5:
        return float("nan")
    return float(np.corrcoef(a[mask], b[mask])[0, 1])
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/diagnostics/test_tail_dependence.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/diagnostics/tail_dependence.py \
        tests/diagnostics/test_tail_dependence.py
git commit -m "feat(diagnostics): exceedance correlation for tail-dependence checks

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 24: Distribution distance — KS + energy distance

**Files:**
- Create: `src/chronos2_demo/diagnostics/distribution.py`
- Create: `tests/diagnostics/test_distribution.py`

Two scalar summaries per series, comparing path-set marginals at a chosen horizon timestep against a realized empirical distribution:
- **KS statistic** — max gap between empirical CDFs.
- **Energy distance** — a weighting-aware alternative that penalizes whole-distribution mismatch, not just the worst point.

The realized distribution comes from a sliding window of historical returns of the matching length.

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np
import pandas as pd
import pytest
from chronos2_demo.diagnostics import distribution as ds
from chronos2_demo.types import PathSet


def _pathset_normal(loc=0.0, scale=1.0, n_paths=2000, horizon=10, n_series=1, seed=0):
    rng = np.random.default_rng(seed)
    paths = rng.normal(loc, scale, size=(n_paths, horizon, n_series))
    weights = np.full(n_paths, 1.0 / n_paths)
    return PathSet(paths=paths, weights=weights,
                   series=[f"S{i}" for i in range(n_series)],
                   dates=pd.bdate_range("2022-07-01", periods=horizon),
                   source="parametric")


def test_ks_zero_when_distributions_match():
    ps = _pathset_normal(seed=0)
    realized_sample = np.random.default_rng(1).normal(0, 1, size=2000)
    stat = ds.ks_at_step(ps, t=5, series="S0", realized_sample=realized_sample)
    assert stat < 0.1


def test_ks_large_when_distributions_differ():
    ps = _pathset_normal(loc=0.0, scale=1.0, seed=0)
    shifted = np.random.default_rng(1).normal(5.0, 1.0, size=2000)
    stat = ds.ks_at_step(ps, t=5, series="S0", realized_sample=shifted)
    assert stat > 0.5


def test_energy_distance_nonnegative_and_zero_on_self():
    ps = _pathset_normal(seed=0)
    sample = ps.paths[:, 5, 0]
    val = ds.energy_distance_at_step(ps, t=5, series="S0", realized_sample=sample)
    assert val >= 0
    assert val < 0.05  # near-zero — same sample


def test_distribution_metrics_reject_unknown_series():
    ps = _pathset_normal(seed=0)
    with pytest.raises(KeyError):
        ds.ks_at_step(ps, t=0, series="Z",
                      realized_sample=np.zeros(10))
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/diagnostics/test_distribution.py -v
```

- [ ] **Step 3: Implement `src/chronos2_demo/diagnostics/distribution.py`**

```python
"""KS and energy-distance summaries between path-set marginals and a realized sample."""
from __future__ import annotations
import numpy as np
from scipy import stats
from chronos2_demo.types import PathSet


def _series_index(pathset: PathSet, name: str) -> int:
    if name not in pathset.series:
        raise KeyError(f"series {name!r} not in pathset.series={pathset.series}")
    return pathset.series.index(name)


def _path_marginal(pathset: PathSet, t: int, series: str) -> np.ndarray:
    j = _series_index(pathset, series)
    return pathset.paths[:, t, j]


def ks_at_step(
    pathset: PathSet, t: int, series: str, realized_sample: np.ndarray
) -> float:
    """Two-sample KS statistic between path-set marginal at t and realized."""
    sample = _path_marginal(pathset, t, series)
    stat, _ = stats.ks_2samp(sample, realized_sample)
    return float(stat)


def energy_distance_at_step(
    pathset: PathSet, t: int, series: str, realized_sample: np.ndarray
) -> float:
    """Two-sample energy distance (Szekely & Rizzo)."""
    sample = _path_marginal(pathset, t, series)
    return float(stats.energy_distance(sample, realized_sample))
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/diagnostics/test_distribution.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/diagnostics/distribution.py \
        tests/diagnostics/test_distribution.py
git commit -m "feat(diagnostics): KS and energy distance vs realized

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

> _Continue with `2026-05-22-plan-a-quant-pipeline-part-3b.md` (Stage 7 — Plotting helpers, Tasks 25–27)._
