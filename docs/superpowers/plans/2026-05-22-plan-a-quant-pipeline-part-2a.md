# Plan A — Part 2a: Stage 2 — Baseline Parametric MC

> **Continuation of** `2026-05-22-plan-a-quant-pipeline.md`. Tasks 7–10. Same TDD pattern.

---

## Stage 2 — Baseline parametric MC

The baseline engine: PCA on factor returns + Hull-White short-rate dynamics + GBM-style FX, Cholesky-driven joint sampling. Returns a `PathSet` with `source="parametric"` and uniform weights.

### Task 7: PCA factor extraction

**Files:**
- Create: `src/chronos2_demo/models/__init__.py`
- Create: `src/chronos2_demo/models/baseline_mc.py` (this task adds only the PCA helper)
- Create: `tests/models/__init__.py`
- Create: `tests/models/test_baseline_mc_pca.py`

- [ ] **Step 1: Write the failing test**

`tests/models/__init__.py`: empty.

`tests/models/test_baseline_mc_pca.py`:
```python
import numpy as np
import pandas as pd
from chronos2_demo.models import baseline_mc


def test_pca_returns_unit_variance_factors_and_loadings():
    rng = np.random.default_rng(0)
    n_obs, n_series = 500, 5
    raw = rng.normal(0, 0.01, size=(n_obs, n_series)).cumsum(axis=0) + 1.0
    panel = pd.DataFrame(raw, columns=[f"S{i}" for i in range(n_series)],
                         index=pd.bdate_range("2020-01-02", periods=n_obs))
    fit = baseline_mc.fit_pca(panel, n_components=3)
    assert fit.loadings.shape == (n_series, 3)
    assert fit.mean.shape == (n_series,)
    assert fit.std.shape == (n_series,)
    # explained variance ratio descending
    evr = fit.explained_variance_ratio
    assert (np.diff(evr) <= 1e-12).all()


def test_pca_components_can_reconstruct_returns_in_log_space():
    rng = np.random.default_rng(1)
    n_obs, n_series = 800, 4
    raw = rng.normal(0, 0.005, size=(n_obs, n_series)).cumsum(axis=0) + 1.0
    panel = pd.DataFrame(raw, columns=list("ABCD"),
                         index=pd.bdate_range("2020-01-02", periods=n_obs))
    fit = baseline_mc.fit_pca(panel, n_components=4)
    # full-rank reconstruction error on standardized log-returns is small
    log_rets = np.log(panel).diff().dropna().values
    standardized = (log_rets - fit.mean) / fit.std
    factors = standardized @ fit.loadings  # (n_obs-1, k)
    recon = factors @ fit.loadings.T
    assert np.linalg.norm(standardized - recon) / np.linalg.norm(standardized) < 0.05
```

- [ ] **Step 2: Run test, confirm fail**

```bash
pytest tests/models/test_baseline_mc_pca.py -v
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `src/chronos2_demo/models/__init__.py`**

```python
# empty
```

- [ ] **Step 4: Implement `src/chronos2_demo/models/baseline_mc.py` (PCA part only)**

```python
"""Parametric joint scenario engine.

Pipeline:
  1. fit_pca: standardize log-returns, extract orthogonal factor loadings.
  2. fit_factor_dynamics: AR(1) per factor (compact stand-in for Hull-White
     for rates factors; GBM-style for FX factors). One config knob.
  3. simulate: sample joint factor paths, project back through loadings,
     re-exponentiate to absolute level space.

This file is split across Tasks 7-10. Task 7 adds fit_pca only.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA


@dataclass(frozen=True)
class PCAFit:
    loadings: np.ndarray      # (n_series, k) orthonormal in feature space
    mean: np.ndarray          # (n_series,)
    std: np.ndarray           # (n_series,)
    explained_variance_ratio: np.ndarray  # (k,) descending
    series: list[str]


def fit_pca(panel: pd.DataFrame, n_components: int) -> PCAFit:
    """Standardize log-returns of `panel` and fit PCA.

    Returns loadings (n_series, k), mean, std (per series), and explained
    variance ratio. Loadings are taken as PCA components.T so that
    `standardized @ loadings == factor_scores`.
    """
    log_rets = np.log(panel).diff().dropna().values  # (T-1, n_series)
    mean = log_rets.mean(axis=0)
    std = log_rets.std(axis=0, ddof=1)
    # Guard against zero-variance series in tiny test panels.
    std = np.where(std < 1e-12, 1.0, std)
    standardized = (log_rets - mean) / std
    pca = PCA(n_components=n_components)
    pca.fit(standardized)
    loadings = pca.components_.T  # (n_series, k)
    return PCAFit(
        loadings=loadings,
        mean=mean,
        std=std,
        explained_variance_ratio=pca.explained_variance_ratio_,
        series=list(panel.columns),
    )
```

- [ ] **Step 5: Run, confirm pass**

```bash
pytest tests/models/test_baseline_mc_pca.py -v
```
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add src/chronos2_demo/models/__init__.py src/chronos2_demo/models/baseline_mc.py \
        tests/models/__init__.py tests/models/test_baseline_mc_pca.py
git commit -m "feat(models): add PCA factor extraction for baseline MC

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 8: AR(1) factor dynamics fit + sampler

**Files:**
- Modify: `src/chronos2_demo/models/baseline_mc.py` (append `FactorDynamics`, `fit_factor_dynamics`, `_sample_factor_paths`)
- Create: `tests/models/test_baseline_mc_dynamics.py`

- [ ] **Step 1: Write the failing test**

```python
import numpy as np
import pandas as pd
from chronos2_demo.models import baseline_mc


def _flat_panel(n=600, k=4, seed=0):
    rng = np.random.default_rng(seed)
    raw = rng.normal(0, 0.005, size=(n, k)).cumsum(axis=0) + 1.0
    return pd.DataFrame(raw, columns=[f"S{i}" for i in range(k)],
                        index=pd.bdate_range("2020-01-02", periods=n))


def test_factor_dynamics_estimates_phi_in_unit_interval():
    panel = _flat_panel()
    pca = baseline_mc.fit_pca(panel, n_components=3)
    dyn = baseline_mc.fit_factor_dynamics(panel, pca)
    assert dyn.phi.shape == (3,)
    assert (np.abs(dyn.phi) < 1.0).all()
    assert (dyn.sigma > 0).all()


def test_sample_factor_paths_shape_and_finiteness():
    panel = _flat_panel()
    pca = baseline_mc.fit_pca(panel, n_components=3)
    dyn = baseline_mc.fit_factor_dynamics(panel, pca)
    paths = baseline_mc._sample_factor_paths(
        dyn, n_paths=100, horizon=63, rng=np.random.default_rng(7)
    )
    assert paths.shape == (100, 63, 3)
    assert np.isfinite(paths).all()


def test_sample_factor_paths_variance_grows_with_horizon():
    panel = _flat_panel()
    pca = baseline_mc.fit_pca(panel, n_components=3)
    dyn = baseline_mc.fit_factor_dynamics(panel, pca)
    paths = baseline_mc._sample_factor_paths(
        dyn, n_paths=2000, horizon=252, rng=np.random.default_rng(11)
    )
    var_t10 = paths[:, 10, :].var(axis=0).sum()
    var_t250 = paths[:, 250, :].var(axis=0).sum()
    assert var_t250 > var_t10 * 5
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/models/test_baseline_mc_dynamics.py -v
```

- [ ] **Step 3: Append to `src/chronos2_demo/models/baseline_mc.py`**

```python
@dataclass(frozen=True)
class FactorDynamics:
    phi: np.ndarray    # (k,) AR(1) coefficient per factor
    sigma: np.ndarray  # (k,) innovation std per factor


def fit_factor_dynamics(panel: pd.DataFrame, pca: PCAFit) -> FactorDynamics:
    """Fit AR(1) per factor: f_t = phi * f_{t-1} + sigma * eps_t."""
    log_rets = np.log(panel).diff().dropna().values
    standardized = (log_rets - pca.mean) / pca.std
    factors = standardized @ pca.loadings  # (T-1, k)
    k = factors.shape[1]
    phi = np.empty(k)
    sigma = np.empty(k)
    for j in range(k):
        x = factors[:-1, j]
        y = factors[1:, j]
        denom = (x * x).sum()
        phi_j = (x * y).sum() / denom if denom > 1e-12 else 0.0
        # Clamp to (-0.999, 0.999) for stability.
        phi_j = float(np.clip(phi_j, -0.999, 0.999))
        resid = y - phi_j * x
        sigma_j = float(np.sqrt(max((resid * resid).mean(), 1e-12)))
        phi[j] = phi_j
        sigma[j] = sigma_j
    return FactorDynamics(phi=phi, sigma=sigma)


def _sample_factor_paths(
    dyn: FactorDynamics,
    n_paths: int,
    horizon: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Draw (n_paths, horizon, k) factor paths starting from f_0 = 0."""
    k = dyn.phi.shape[0]
    eps = rng.standard_normal(size=(n_paths, horizon, k))
    paths = np.empty_like(eps)
    f_prev = np.zeros((n_paths, k))
    for t in range(horizon):
        f_t = dyn.phi * f_prev + dyn.sigma * eps[:, t, :]
        paths[:, t, :] = f_t
        f_prev = f_t
    return paths
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/models/test_baseline_mc_dynamics.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/models/baseline_mc.py tests/models/test_baseline_mc_dynamics.py
git commit -m "feat(models): add AR(1) factor dynamics fit and path sampler

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 9: End-to-end `simulate_baseline` returning a PathSet

**Files:**
- Modify: `src/chronos2_demo/models/baseline_mc.py` (append `simulate_baseline`)
- Create: `tests/models/test_baseline_mc_simulate.py`

- [ ] **Step 1: Write the failing test**

```python
import numpy as np
import pandas as pd
import pytest
from chronos2_demo.models import baseline_mc
from chronos2_demo.types import PathSet


def _panel(n=600, k=4, seed=0):
    rng = np.random.default_rng(seed)
    raw = rng.normal(0, 0.005, size=(n, k)).cumsum(axis=0) + 1.0
    return pd.DataFrame(raw, columns=list("ABCD"),
                        index=pd.bdate_range("2020-01-02", periods=n))


def test_simulate_baseline_returns_pathset_with_correct_shape():
    panel = _panel()
    ps = baseline_mc.simulate_baseline(
        panel, as_of="2022-01-03", horizon=63, n_paths=500, n_components=3, seed=0
    )
    assert isinstance(ps, PathSet)
    assert ps.source == "parametric"
    assert ps.paths.shape == (500, 63, 4)
    assert ps.series == ["A", "B", "C", "D"]
    assert np.isclose(ps.weights.sum(), 1.0)


def test_simulate_baseline_paths_start_near_as_of_levels():
    panel = _panel()
    as_of = "2022-01-03"
    ps = baseline_mc.simulate_baseline(
        panel, as_of=as_of, horizon=10, n_paths=200, n_components=3, seed=0
    )
    levels_at_as_of = panel.loc[as_of].values  # (4,)
    first_step = ps.paths[:, 0, :].mean(axis=0)
    rel_err = np.abs(first_step - levels_at_as_of) / np.abs(levels_at_as_of)
    assert (rel_err < 0.05).all()


def test_simulate_baseline_is_deterministic_under_same_seed():
    panel = _panel()
    a = baseline_mc.simulate_baseline(panel, "2022-01-03", 30, 100, 3, seed=42)
    b = baseline_mc.simulate_baseline(panel, "2022-01-03", 30, 100, 3, seed=42)
    np.testing.assert_array_equal(a.paths, b.paths)
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/models/test_baseline_mc_simulate.py -v
```

- [ ] **Step 3: Append to `src/chronos2_demo/models/baseline_mc.py`**

```python
from chronos2_demo.types import PathSet


def simulate_baseline(
    panel: pd.DataFrame,
    as_of: str,
    horizon: int,
    n_paths: int,
    n_components: int,
    seed: int = 0,
) -> PathSet:
    """Simulate joint factor paths and project to absolute-level space.

    Steps:
      1. Fit PCA + factor dynamics on `panel` history up to and including `as_of`.
      2. Sample (n_paths, horizon, k) factor paths.
      3. Project to standardized log-return space via loadings.T.
      4. Reverse standardization, cumulate, exponentiate, multiply by S_{as_of}.
    """
    history = panel.loc[:pd.Timestamp(as_of)]
    pca = fit_pca(history, n_components=n_components)
    dyn = fit_factor_dynamics(history, pca)
    rng = np.random.default_rng(seed)
    factor_paths = _sample_factor_paths(dyn, n_paths, horizon, rng)  # (N, H, k)

    # Project factors back to standardized log-return space.
    log_rets = np.einsum("nhk,sk->nhs", factor_paths, pca.loadings)
    # De-standardize: x = log_ret * std + mean.
    log_rets = log_rets * pca.std + pca.mean
    # Cumulate to get log levels relative to S_{as_of}.
    cum_log = np.cumsum(log_rets, axis=1)
    s0 = panel.loc[pd.Timestamp(as_of)].values  # (n_series,)
    levels = s0 * np.exp(cum_log)

    horizon_dates = pd.bdate_range(
        start=pd.Timestamp(as_of) + pd.tseries.offsets.BDay(1), periods=horizon
    )
    weights = np.full(n_paths, 1.0 / n_paths)
    return PathSet(
        paths=levels,
        weights=weights,
        series=list(panel.columns),
        dates=horizon_dates,
        source="parametric",
    )
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/models/test_baseline_mc_simulate.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/models/baseline_mc.py tests/models/test_baseline_mc_simulate.py
git commit -m "feat(models): end-to-end simulate_baseline returning PathSet

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 10: Cross-asset coupling sanity test (integration test)

**Files:**
- Create: `tests/models/test_baseline_mc_coupling.py`

The factor dynamics are independent per factor, but the *loadings* induce cross-series correlation. This test pins that the simulator preserves an empirical-style correlation structure on a panel with known coupling.

- [ ] **Step 1: Write the test**

```python
import numpy as np
import pandas as pd
from chronos2_demo.models import baseline_mc


def test_simulated_cross_correlation_matches_empirical_sign():
    """When two series are positively correlated in history, simulated
    log-returns should also be positively correlated on average."""
    rng = np.random.default_rng(123)
    n = 800
    common = rng.normal(0, 0.01, size=n).cumsum()
    a = common + rng.normal(0, 0.001, size=n).cumsum()
    b = common + rng.normal(0, 0.001, size=n).cumsum()
    c = -common + rng.normal(0, 0.001, size=n).cumsum()
    panel = pd.DataFrame({"A": np.exp(a/100), "B": np.exp(b/100), "C": np.exp(c/100)},
                         index=pd.bdate_range("2020-01-02", periods=n))

    ps = baseline_mc.simulate_baseline(panel, "2022-01-03", 252, 2000, 3, seed=5)
    log_rets = np.diff(np.log(ps.paths), axis=1)  # (N, H-1, n_series)
    # Average correlation across paths.
    flat = log_rets.reshape(-1, log_rets.shape[-1])
    corr = np.corrcoef(flat.T)
    assert corr[0, 1] > 0.5    # A,B positively correlated
    assert corr[0, 2] < -0.3   # A,C negatively correlated
```

- [ ] **Step 2: Run, confirm pass**

```bash
pytest tests/models/test_baseline_mc_coupling.py -v
```
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/models/test_baseline_mc_coupling.py
git commit -m "test(models): pin cross-asset correlation behavior of baseline MC

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

> _Continue with `2026-05-22-plan-a-quant-pipeline-part-2b.md` (Stage 3 — Chronos-2 client & SageMaker deployment, Tasks 11–14)._
