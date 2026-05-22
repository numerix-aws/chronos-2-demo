# Plan A — Part 3b: Stage 7 — Plotting Helpers

> **Continuation of** `2026-05-22-plan-a-quant-pipeline-part-3a.md`. Tasks 25–27.

---

## Stage 7 — Plotting helpers

Plotting is **deliberately thin**. Each helper takes already-computed numeric inputs (PathSets, EE/PFE/ES dicts, regime weights) and returns a `matplotlib.figure.Figure`. Tests assert on figure structure (axes, titles, line counts), not pixel-level appearance — that keeps the suite hermetic and stable.

The notebook (Stage 8) imports and composes these helpers. The agent UI (Plan B) will reuse the same numeric inputs but render via Cloudscape on the React side; these helpers exist for the notebook + screenshot path.

### Task 25: PFE overlay plot (baseline vs augmented)

**Files:**
- Create: `src/chronos2_demo/plotting/__init__.py`
- Create: `src/chronos2_demo/plotting/pfe_overlay.py`
- Create: `tests/plotting/__init__.py`
- Create: `tests/plotting/test_pfe_overlay.py`

The money-shot chart: PFE@97.5% across the horizon, baseline (parametric) vs augmented (blended), with the gap shaded between them.

- [ ] **Step 1: Write the failing tests**

`tests/plotting/__init__.py`: empty.

`tests/plotting/test_pfe_overlay.py`:
```python
import matplotlib
matplotlib.use("Agg")  # headless
import numpy as np
import pandas as pd
import pytest
from chronos2_demo.plotting import pfe_overlay as p


def _metrics(horizon=21, base=1.0, scale=1.0):
    dates = pd.bdate_range("2022-07-01", periods=horizon)
    return {
        "ee":      np.linspace(0, 1, horizon) * base * scale,
        "pfe_975": np.linspace(0, 3, horizon) * base * scale,
        "es_975":  np.linspace(0, 4, horizon) * base * scale,
        "dates":   dates,
    }


def test_plot_pfe_overlay_returns_figure_with_two_lines():
    fig = p.plot_pfe_overlay(
        baseline=_metrics(scale=1.0),
        augmented=_metrics(scale=1.4),
        title="PFE overlay",
    )
    ax = fig.axes[0]
    labels = [l.get_label() for l in ax.get_lines()]
    assert "baseline" in labels
    assert "augmented" in labels
    assert ax.get_title() == "PFE overlay"


def test_plot_pfe_overlay_shades_gap_between_curves():
    fig = p.plot_pfe_overlay(
        baseline=_metrics(scale=1.0),
        augmented=_metrics(scale=1.4),
        title="x",
    )
    ax = fig.axes[0]
    # fill_between produces a PolyCollection
    from matplotlib.collections import PolyCollection
    has_fill = any(isinstance(c, PolyCollection) for c in ax.collections)
    assert has_fill


def test_plot_pfe_overlay_rejects_misaligned_dates():
    bad_metrics = _metrics(horizon=21)
    bad_metrics["dates"] = pd.bdate_range("2023-01-01", periods=21)
    with pytest.raises(ValueError, match="align"):
        p.plot_pfe_overlay(baseline=_metrics(), augmented=bad_metrics, title="x")
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/plotting/test_pfe_overlay.py -v
```

- [ ] **Step 3: Implement files**

`src/chronos2_demo/plotting/__init__.py`: empty.

`src/chronos2_demo/plotting/pfe_overlay.py`:
```python
"""PFE overlay: baseline vs augmented across horizon, with gap shading.

Inputs are the dicts returned by `pricing.exposure.compute_metrics`:
  {"ee": ndarray, "pfe_975": ndarray, "es_975": ndarray, "dates": DatetimeIndex}
"""
from __future__ import annotations
import matplotlib.pyplot as plt
import pandas as pd


def plot_pfe_overlay(
    baseline: dict,
    augmented: dict,
    title: str,
    metric: str = "pfe_975",
) -> "plt.Figure":
    if not pd.DatetimeIndex(baseline["dates"]).equals(pd.DatetimeIndex(augmented["dates"])):
        raise ValueError("baseline and augmented dates must align")
    dates = pd.DatetimeIndex(baseline["dates"])
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(dates, baseline[metric], label="baseline", color="tab:blue")
    ax.plot(dates, augmented[metric], label="augmented", color="tab:orange")
    ax.fill_between(dates, baseline[metric], augmented[metric],
                    color="tab:orange", alpha=0.15)
    ax.set_title(title)
    ax.set_xlabel("date")
    ax.set_ylabel(metric)
    ax.legend(loc="best")
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/plotting/test_pfe_overlay.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/plotting/__init__.py \
        src/chronos2_demo/plotting/pfe_overlay.py \
        tests/plotting/__init__.py tests/plotting/test_pfe_overlay.py
git commit -m "feat(plotting): PFE overlay (baseline vs augmented) with gap fill

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 26: Joint path-sample fan chart

**Files:**
- Create: `src/chronos2_demo/plotting/path_samples.py`
- Create: `tests/plotting/test_path_samples.py`

For one chosen series, plot a thinned subset of paths plus the weighted [5%, 95%] band. This is the "look at the actual scenarios" plot.

- [ ] **Step 1: Write the failing tests**

```python
import matplotlib
matplotlib.use("Agg")
import numpy as np
import pandas as pd
import pytest
from chronos2_demo.plotting import path_samples as p
from chronos2_demo.types import PathSet


def _ps(n_paths=200, horizon=21, n_series=2, seed=0):
    rng = np.random.default_rng(seed)
    paths = rng.normal(1.0, 0.05, size=(n_paths, horizon, n_series))
    weights = np.full(n_paths, 1.0 / n_paths)
    return PathSet(paths=paths, weights=weights,
                   series=[f"S{i}" for i in range(n_series)],
                   dates=pd.bdate_range("2022-07-01", periods=horizon),
                   source="parametric")


def test_fan_chart_renders_band_and_thinned_paths():
    ps = _ps(n_paths=200)
    fig = p.plot_path_fan(ps, series="S0", n_path_samples=20, title="x")
    ax = fig.axes[0]
    # 20 sampled paths + 1 line for median (optional) — at least 20 lines.
    assert len(ax.get_lines()) >= 20
    from matplotlib.collections import PolyCollection
    assert any(isinstance(c, PolyCollection) for c in ax.collections)


def test_fan_chart_rejects_unknown_series():
    ps = _ps()
    with pytest.raises(KeyError):
        p.plot_path_fan(ps, series="ZZ", n_path_samples=5, title="x")


def test_fan_chart_caps_n_path_samples_at_n_paths():
    ps = _ps(n_paths=10)
    fig = p.plot_path_fan(ps, series="S0", n_path_samples=100, title="x")
    ax = fig.axes[0]
    # Path lines drawn, regardless: shouldn't exceed n_paths.
    n_path_lines = sum(1 for l in ax.get_lines() if l.get_label() == "_path")
    assert n_path_lines <= 10
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/plotting/test_path_samples.py -v
```

- [ ] **Step 3: Implement `src/chronos2_demo/plotting/path_samples.py`**

```python
"""Joint path-sample fan chart for a single series."""
from __future__ import annotations
import numpy as np
import matplotlib.pyplot as plt
from chronos2_demo.types import PathSet


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    order = np.argsort(values)
    v = values[order]
    w = weights[order]
    cw = np.cumsum(w)
    cw /= cw[-1]
    return float(np.interp(q, cw, v))


def plot_path_fan(
    pathset: PathSet,
    series: str,
    n_path_samples: int,
    title: str,
    q_low: float = 0.05,
    q_high: float = 0.95,
) -> "plt.Figure":
    if series not in pathset.series:
        raise KeyError(f"unknown series {series!r}")
    j = pathset.series.index(series)
    paths_s = pathset.paths[:, :, j]  # (n_paths, horizon)
    horizon = paths_s.shape[1]

    n_show = min(n_path_samples, paths_s.shape[0])
    sample_idx = np.linspace(0, paths_s.shape[0] - 1, n_show).astype(int)

    lo = np.array([_weighted_quantile(paths_s[:, t], pathset.weights, q_low)
                   for t in range(horizon)])
    hi = np.array([_weighted_quantile(paths_s[:, t], pathset.weights, q_high)
                   for t in range(horizon)])

    fig, ax = plt.subplots(figsize=(8, 4))
    for i in sample_idx:
        ax.plot(pathset.dates, paths_s[i], color="gray", alpha=0.25,
                linewidth=0.5, label="_path")
    ax.fill_between(pathset.dates, lo, hi, color="tab:blue", alpha=0.2,
                    label=f"[{int(q_low*100)}%, {int(q_high*100)}%]")
    ax.set_title(title)
    ax.set_xlabel("date")
    ax.set_ylabel(series)
    ax.legend(loc="best")
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/plotting/test_path_samples.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/plotting/path_samples.py \
        tests/plotting/test_path_samples.py
git commit -m "feat(plotting): joint path-sample fan chart per series

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 27: Regime ribbon strip

**Files:**
- Create: `src/chronos2_demo/plotting/regime_ribbon.py`
- Create: `tests/plotting/test_regime_ribbon.py`

A thin colored strip plotting `w_stress` (continuous) over time below a chosen anchor chart, plus shading for stress-labeled windows. Used in the notebook to align "what regime were we in" with "what did the engines do."

- [ ] **Step 1: Write the failing tests**

```python
import matplotlib
matplotlib.use("Agg")
import numpy as np
import pandas as pd
import pytest
from chronos2_demo.plotting import regime_ribbon as p


def test_regime_ribbon_renders_with_w_stress_line_and_threshold_shading():
    idx = pd.bdate_range("2022-01-03", periods=100)
    w = pd.Series(np.linspace(0.1, 0.9, 100), index=idx, name="w_stress")
    fig = p.plot_regime_ribbon(w, threshold=0.7, title="regime")
    ax = fig.axes[0]
    assert ax.get_title() == "regime"
    assert any(l.get_label() == "w_stress" for l in ax.get_lines())
    # Threshold line drawn somewhere as a second line.
    assert sum(1 for l in ax.get_lines()) >= 2


def test_regime_ribbon_shades_stress_windows():
    idx = pd.bdate_range("2022-01-03", periods=50)
    arr = np.array([0.2] * 20 + [0.9] * 15 + [0.2] * 15)
    w = pd.Series(arr, index=idx, name="w_stress")
    fig = p.plot_regime_ribbon(w, threshold=0.7, title="x")
    ax = fig.axes[0]
    from matplotlib.collections import PolyCollection
    fills = [c for c in ax.collections if isinstance(c, PolyCollection)]
    assert len(fills) >= 1


def test_regime_ribbon_rejects_unindexed_input():
    arr = np.linspace(0, 1, 50)
    with pytest.raises(TypeError):
        p.plot_regime_ribbon(arr, threshold=0.7, title="x")
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/plotting/test_regime_ribbon.py -v
```

- [ ] **Step 3: Implement `src/chronos2_demo/plotting/regime_ribbon.py`**

```python
"""Regime ribbon strip — w_stress over time with threshold shading."""
from __future__ import annotations
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def plot_regime_ribbon(
    w_stress: pd.Series,
    threshold: float,
    title: str,
) -> "plt.Figure":
    if not isinstance(w_stress, pd.Series):
        raise TypeError("w_stress must be a pandas Series indexed by date")
    fig, ax = plt.subplots(figsize=(8, 1.6))
    ax.plot(w_stress.index, w_stress.values, color="tab:purple", label="w_stress")
    ax.axhline(threshold, color="black", linestyle="--", linewidth=0.8,
               label=f"threshold={threshold}")
    # Shade contiguous stress runs.
    above = (w_stress.values >= threshold).astype(int)
    if above.any():
        boundaries = np.diff(np.concatenate([[0], above, [0]]))
        starts = np.where(boundaries == 1)[0]
        ends = np.where(boundaries == -1)[0]
        for s, e in zip(starts, ends):
            ax.axvspan(w_stress.index[s], w_stress.index[min(e, len(w_stress) - 1)],
                       color="tab:red", alpha=0.15)
    ax.set_ylim(0, 1)
    ax.set_title(title)
    ax.legend(loc="upper left", fontsize=8)
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/plotting/test_regime_ribbon.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/plotting/regime_ribbon.py \
        tests/plotting/test_regime_ribbon.py
git commit -m "feat(plotting): regime ribbon strip with threshold shading

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

> _Continue with `2026-05-22-plan-a-quant-pipeline-part-3c.md` (Stages 8–9 — Headline notebook + README & pinned numbers, Tasks 28–30)._
