# Plan A — Part 2b: Stage 3 — Chronos-2 Client & AutoGluon Cloud Deployment

> **Continuation of** `2026-05-22-plan-a-quant-pipeline-part-2a.md`. Tasks 11–14.

---

## Stage 3 — Chronos-2 client & AutoGluon Cloud deployment

The Chronos-2 client wraps the **real `amazon/chronos-2` model deployed via AutoGluon Cloud** (`autogluon.cloud.TimeSeriesFoundationModel(model_id="chronos-2")`). AutoGluon Cloud gives us one API across **real-time, serverless, and batch** inference on SageMaker; the demo defaults to a **serverless** endpoint (CPU, scales to zero between demos — the spec §9 "stoppable between demos" goal, with no idle GPU cost). Real endpoint deployment lives in `scripts/deploy_chronos2_endpoint.py`.

**Client contract (locked — AutoGluon endpoint protocol):**
- `Chronos2Client.predict(...)` builds a **long-format DataFrame** (`item_id`, `timestamp`, `target`, plus covariate columns) from the lookback panel and calls the injected AutoGluon endpoint's `predict(data=..., target="target", id_column="item_id", timestamp_column="timestamp", prediction_length=horizon, known_covariates=...)`.
- AutoGluon returns a **long-format quantile DataFrame**: columns `item_id`, `timestamp`, `mean`, and the quantile columns `"0.1" … "0.9"`. These are **per-series quantiles**, NOT sample paths.

**Endpoint-agnostic seam:** `Chronos2Client` takes an injected `endpoint` object exposing `.predict(data, **kwargs) -> DataFrame` (the AutoGluon `TimeSeriesEndpoint` / cloud-predictor in production; a fake in tests). This keeps the **core package and the test suite free of the heavy `autogluon-cloud` import** — only the deploy script and the Fargate `run_chronos2` task (Plan B) construct a real endpoint. Tests inject a fake that returns a quantile DataFrame.

**Why the client still reconstructs paths:** AutoGluon/Chronos-2 returns quantiles, not trajectories, and per series independently. PFE/exposure needs joint, cross-series-correlated paths. So the client turns the quantile block into `(n_paths, horizon, n_series)` joint paths **client-side** via inverse-CDF marginal sampling coupled by a Gaussian copula whose correlation is estimated from the **same lookback window** both engines share (preserving the spec §6 fairness invariant and mirroring the Cholesky-driven joint sampling in `baseline_mc.py`). This reconstruction is the load-bearing modeling decision; it lives in `chronos2_client.py` alongside the transport so the `PathSet` contract downstream is unchanged.

The wrapper builds the request frame, calls the endpoint (retrying transient errors), parses the quantile frame, reconstructs paths, and returns a `PathSet`.

### Task 11: AutoGluon request-frame builder + quantile-frame decoder

**Files:**
- Create: `src/chronos2_demo/models/chronos2_client.py` (frame builder/decoder + dataclasses only)
- Create: `tests/models/test_chronos2_client_payload.py`

`Q_LEVELS` (the Chronos-2 default quantile grid) is the single source of truth for both the request `quantile_levels` and decoding the returned quantile columns. `build_request_frame` turns the wide lookback panel into AutoGluon's **long format** (`item_id` = series name, `timestamp`, `target`, plus covariate columns broadcast across items). The conditioning narrative is encoded as a `__anchor` known-covariate — a faithful pass-through of the existing demo semantics, not new scope.

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np
import pandas as pd
import pytest
from chronos2_demo.models import chronos2_client as c2


def _panel():
    idx = pd.bdate_range("2022-01-03", periods=20)
    return pd.DataFrame(
        np.arange(20 * 3).reshape(20, 3) + 1.0,
        index=idx,
        columns=["A", "B", "C"],
    )


def test_build_request_frame_long_format():
    panel = _panel()
    frame, known = c2.build_request_frame(panel, horizon=10, covariates=None,
                                          conditioning=None)
    # Long format: 20 rows x 3 series = 60 rows; required columns present.
    assert set(["item_id", "timestamp", "target"]).issubset(frame.columns)
    assert len(frame) == 60
    assert sorted(frame["item_id"].unique()) == ["A", "B", "C"]
    a_rows = frame[frame["item_id"] == "A"].sort_values("timestamp")
    assert a_rows["target"].tolist() == panel["A"].tolist()
    assert known is None


def test_build_request_frame_includes_covariates():
    panel = _panel()
    cov = pd.DataFrame(np.zeros((20, 2)) + 0.5, index=panel.index,
                       columns=["VIX", "MOVE"])
    frame, known = c2.build_request_frame(panel, horizon=10, covariates=cov,
                                          conditioning=None)
    assert "VIX" in frame.columns and "MOVE" in frame.columns
    assert (frame["VIX"] == 0.5).all()


def test_build_request_frame_rejects_misaligned_covariates():
    panel = _panel()
    cov = pd.DataFrame(np.zeros((19, 2)), index=panel.index[:19],
                       columns=["VIX", "MOVE"])
    with pytest.raises(ValueError, match="align"):
        c2.build_request_frame(panel, horizon=10, covariates=cov,
                               conditioning=None)


def test_build_request_frame_encodes_conditioning_as_known_covariate():
    panel = _panel()
    cond = c2.Conditioning(series_shifts={"A": 0.1}, n_anchor_days=3)
    frame, known = c2.build_request_frame(panel, horizon=10, covariates=None,
                                          conditioning=cond)
    # Known-covariate frame carries the per-series anchor over the horizon.
    assert known is not None
    a_future = known[known["item_id"] == "A"]
    assert len(a_future) == 10
    assert (a_future["anchor"].head(3) == 0.1).all()
    assert (a_future["anchor"].iloc[3:] == 0.0).all()


def test_decode_response_returns_quantile_block():
    # AutoGluon long-format quantile frame: 2 series x horizon 4.
    rows = []
    ts = pd.bdate_range("2022-02-01", periods=4)
    for s, item in enumerate(["A", "B"]):
        for t in range(4):
            row = {"item_id": item, "timestamp": ts[t], "mean": float(s)}
            for ql in c2.Q_LEVELS:
                row[str(ql)] = float(s) + ql
            rows.append(row)
    frame = pd.DataFrame(rows)
    q_levels, Q = c2.decode_response(frame, series=["A", "B"])
    assert q_levels == c2.Q_LEVELS
    assert Q.shape == (2, 4, len(c2.Q_LEVELS))
    j90 = c2.Q_LEVELS.index(0.9)
    assert np.allclose(Q[1, :, j90], 1.9)


def test_decode_response_rejects_missing_quantile_columns():
    frame = pd.DataFrame({"item_id": ["A"], "timestamp": [pd.Timestamp("2022-02-01")],
                          "mean": [1.0]})
    with pytest.raises(KeyError):
        c2.decode_response(frame, series=["A"])
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/models/test_chronos2_client_payload.py -v
```

- [ ] **Step 3: Implement `src/chronos2_demo/models/chronos2_client.py` (this task adds only the frame builder/decoder)**

```python
"""Client for the Chronos-2 endpoint deployed via AutoGluon Cloud.

AutoGluon endpoint protocol (amazon/chronos-2):
  Request:  a long-format DataFrame (item_id, timestamp, target, [covariates...])
            plus an optional `known_covariates` future-frame; called as
            endpoint.predict(data=frame, target="target", id_column="item_id",
            timestamp_column="timestamp", prediction_length=H,
            known_covariates=known).
  Response: a long-format DataFrame with columns item_id, timestamp, mean, and
            the quantile columns "0.1".."0.9" -- per-series QUANTILES, not paths.

The endpoint returns quantiles, not paths. `Chronos2Client.predict` (Task 12)
turns the quantile block into joint sample paths via a lookback Gaussian copula.

This file is split across Tasks 11-13. Task 11 adds the frame builder/decoder.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import numpy as np
import pandas as pd

# Fixed quantile grid (Chronos-2 default). Single source of truth for both the
# request quantile_levels and decoding the returned quantile columns.
Q_LEVELS: list[float] = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]


@dataclass(frozen=True)
class Conditioning:
    """User-supplied stress narrative passed as an `anchor` known covariate.

    `series_shifts` is a per-series additive anchor applied over the first
    `n_anchor_days` of the forecast horizon (in absolute level units).
    """
    series_shifts: dict[str, float]
    n_anchor_days: int

    def to_jsonable(self) -> dict[str, Any]:
        return {"series_shifts": dict(self.series_shifts),
                "n_anchor_days": int(self.n_anchor_days)}


def build_request_frame(
    context: pd.DataFrame,
    horizon: int,
    covariates: pd.DataFrame | None,
    conditioning: Conditioning | None,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Wide lookback panel -> AutoGluon long-format (data_frame, known_covariates).

    `data_frame` has columns item_id, timestamp, target (+ covariate columns
    broadcast across items). `known_covariates`, when conditioning is supplied,
    carries a per-series `anchor` over the future horizon dates.
    """
    if covariates is not None and not context.index.equals(covariates.index):
        raise ValueError("covariates index must align with context index")

    blocks = []
    for series in context.columns:
        block = pd.DataFrame({
            "item_id": series,
            "timestamp": context.index,
            "target": context[series].values,
        })
        if covariates is not None:
            for c in covariates.columns:
                block[c] = covariates[c].values
        blocks.append(block)
    data_frame = pd.concat(blocks, ignore_index=True)

    known = None
    if conditioning is not None:
        future_dates = pd.bdate_range(
            start=context.index[-1] + pd.tseries.offsets.BDay(1), periods=horizon
        )
        kblocks = []
        for series in context.columns:
            shift = conditioning.series_shifts.get(series, 0.0)
            anchor = np.zeros(horizon)
            anchor[: min(conditioning.n_anchor_days, horizon)] = shift
            kblocks.append(pd.DataFrame({
                "item_id": series, "timestamp": future_dates, "anchor": anchor,
            }))
        known = pd.concat(kblocks, ignore_index=True)
    return data_frame, known


def decode_response(frame: pd.DataFrame, series: list[str]) -> tuple[list[float], np.ndarray]:
    """Long-format quantile frame -> (q_levels, (n_series, horizon, n_q)).

    `series` fixes the output order (matching the request panel columns).
    """
    missing = [str(ql) for ql in Q_LEVELS if str(ql) not in frame.columns]
    if missing:
        raise KeyError(f"response missing quantile columns: {missing}")
    horizon = len(frame[frame["item_id"] == series[0]])
    Q = np.empty((len(series), horizon, len(Q_LEVELS)), dtype=float)
    for s, item in enumerate(series):
        rows = frame[frame["item_id"] == item].sort_values("timestamp")
        for j, ql in enumerate(Q_LEVELS):
            Q[s, :, j] = rows[str(ql)].to_numpy(dtype=float)
    return Q_LEVELS, Q
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/models/test_chronos2_client_payload.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/models/chronos2_client.py tests/models/test_chronos2_client_payload.py
git commit -m "feat(chronos2): AutoGluon long-format request frame + quantile decoder

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 12: Path reconstruction + endpoint invocation with retries (mocked)

**Files:**
- Modify: `src/chronos2_demo/models/chronos2_client.py` (append the copula reconstruction helpers + `Chronos2Client`)
- Create: `tests/models/test_chronos2_client_invoke.py`

The endpoint returns a quantile DataFrame; `predict` reconstructs joint paths. Two pure helpers do the modeling work (isolated and unit-tested so the quant team can inspect/replace them), then `predict` chains build-frame → endpoint.predict (with retries) → decode → reconstruct. The client holds an **injected endpoint** exposing `.predict(data, target, id_column, timestamp_column, prediction_length, known_covariates) -> DataFrame` — a fake in tests, the AutoGluon endpoint in production — so this module never imports `autogluon-cloud`.

1. `lookback_correlation(panel)` — Pearson correlation of lookback log-returns, nearest-PD guarded; identity fallback for degenerate (<3 row) lookbacks.
2. `reconstruct_paths(q_levels, quantile_values, correlation, n_paths, seed)` — per-(series, step) inverse-CDF of a uniform draw against the returned quantile curve, with the uniforms coupled across series by a Gaussian copula (one uniform per (path, series), shared across the horizon).

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np
import pandas as pd
import pytest
from chronos2_demo.models import chronos2_client as c2


def _panel(n=120, n_series=3):
    idx = pd.bdate_range("2022-01-03", periods=n)
    rng = np.random.default_rng(0)
    data = np.exp(rng.normal(0, 0.01, size=(n, n_series)).cumsum(axis=0))
    return pd.DataFrame(data, index=idx, columns=["A", "B", "C"][:n_series])


class _FakeEndpoint:
    """Stands in for an AutoGluon TimeSeriesEndpoint.

    Returns a long-format quantile frame for whatever items/horizon it is asked
    to forecast. `fail_times` raises on the first N calls to exercise retries.
    """
    def __init__(self, fail_times=0):
        self.fail_times = fail_times
        self.calls = 0

    def predict(self, data, target, id_column, timestamp_column,
                prediction_length, known_covariates=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("transient endpoint error")
        items = list(dict.fromkeys(data[id_column]))
        future = pd.bdate_range("2022-07-01", periods=prediction_length)
        rows = []
        for item in items:
            for t in range(prediction_length):
                row = {id_column: item, timestamp_column: future[t], "mean": 1.0}
                for ql in c2.Q_LEVELS:
                    row[str(ql)] = 1.0 + (ql - 0.5) * 0.1
                rows.append(row)
        return pd.DataFrame(rows)


# --- reconstruction helpers ---

def test_lookback_correlation_is_symmetric_psd():
    R = c2.lookback_correlation(_panel())
    assert R.shape == (3, 3)
    assert np.allclose(R, R.T)
    assert np.all(np.linalg.eigvalsh(R) > -1e-8)
    assert np.allclose(np.diag(R), 1.0)


def test_lookback_correlation_degenerate_falls_back_to_identity():
    R = c2.lookback_correlation(_panel(n=2))
    assert np.allclose(R, np.eye(3))


def test_reconstruct_paths_shape_and_marginal_median():
    q_levels = np.array(c2.Q_LEVELS)
    n_series, horizon = 3, 10
    Q = np.empty((n_series, horizon, len(q_levels)))
    for s in range(n_series):
        for j, ql in enumerate(q_levels):
            Q[s, :, j] = 1.0 + (ql - 0.5) * 0.1
    paths = c2.reconstruct_paths(q_levels, Q, np.eye(3), n_paths=5000, seed=0)
    assert paths.shape == (5000, horizon, n_series)
    med = np.median(paths, axis=0)
    assert np.allclose(med, 1.0, atol=0.01)


def test_reconstruct_paths_induces_cross_series_correlation():
    q_levels = np.array(c2.Q_LEVELS)
    Q = np.empty((2, 5, len(q_levels)))
    for s in range(2):
        for j, ql in enumerate(q_levels):
            Q[s, :, j] = 1.0 + (ql - 0.5) * 0.1
    R = np.array([[1.0, 0.8], [0.8, 1.0]])
    paths = c2.reconstruct_paths(q_levels, Q, R, n_paths=8000, seed=2)
    rho = np.corrcoef(paths[:, -1, 0], paths[:, -1, 1])[0, 1]
    assert rho > 0.6


def test_reconstruct_paths_is_deterministic_under_seed():
    q_levels = np.array(c2.Q_LEVELS)
    Q = np.ones((3, 4, len(q_levels)))
    p1 = c2.reconstruct_paths(q_levels, Q, np.eye(3), n_paths=100, seed=7)
    p2 = c2.reconstruct_paths(q_levels, Q, np.eye(3), n_paths=100, seed=7)
    assert np.array_equal(p1, p2)


# --- client transport + reconstruction integration ---

def test_client_invokes_endpoint_and_reconstructs_paths():
    ep = _FakeEndpoint()
    client = c2.Chronos2Client(endpoint=ep)
    out = client.predict(_panel(), horizon=30, n_samples=64)
    assert out.shape == (64, 30, 3)
    assert ep.calls == 1


def test_client_retries_on_transient_error():
    ep = _FakeEndpoint(fail_times=1)
    client = c2.Chronos2Client(endpoint=ep, max_retries=2, retry_sleep=0.0)
    out = client.predict(_panel(), horizon=5, n_samples=8)
    assert out.shape == (8, 5, 3)
    assert ep.calls == 2


def test_client_gives_up_after_max_retries():
    ep = _FakeEndpoint(fail_times=99)
    client = c2.Chronos2Client(endpoint=ep, max_retries=2, retry_sleep=0.0)
    with pytest.raises(RuntimeError):
        client.predict(_panel(), horizon=5, n_samples=8)
    assert ep.calls == 3  # initial + 2 retries
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/models/test_chronos2_client_invoke.py -v
```

- [ ] **Step 3: Append to `src/chronos2_demo/models/chronos2_client.py`**

```python
import time
from typing import Any, Optional, Protocol
from scipy.stats import norm

_EIG_FLOOR = 1e-6


def lookback_correlation(panel: pd.DataFrame) -> np.ndarray:
    """Pearson correlation of lookback log-returns, nearest-PD guarded.

    Degenerate lookbacks (fewer than 3 return rows) fall back to identity
    (independent series).
    """
    n_series = panel.shape[1]
    log_rets = np.log(panel.clip(lower=1e-6)).diff().dropna().values
    if log_rets.shape[0] < 3:
        return np.eye(n_series)
    R = np.corrcoef(log_rets, rowvar=False)
    R = np.nan_to_num(R, nan=0.0)
    np.fill_diagonal(R, 1.0)
    # Nearest-PD guard: clip eigenvalues at a floor, rescale to unit diagonal.
    vals, vecs = np.linalg.eigh((R + R.T) / 2.0)
    vals = np.clip(vals, _EIG_FLOOR, None)
    R = vecs @ np.diag(vals) @ vecs.T
    d = np.sqrt(np.diag(R))
    R = R / np.outer(d, d)
    np.fill_diagonal(R, 1.0)
    return R


def reconstruct_paths(
    q_levels: np.ndarray,
    quantile_values: np.ndarray,
    correlation: np.ndarray,
    n_paths: int,
    seed: int = 0,
) -> np.ndarray:
    """Sample (n_paths, horizon, n_series) joint level paths.

    q_levels: (n_q,) ascending quantile levels in (0, 1).
    quantile_values: (n_series, horizon, n_q) quantile curves from the endpoint.
    correlation: (n_series, n_series) cross-series correlation for the copula.
    """
    n_series, horizon, _ = quantile_values.shape
    rng = np.random.default_rng(seed)
    # Gaussian copula: one uniform per (path, series), shared across horizon.
    chol = np.linalg.cholesky(correlation)
    u = norm.cdf(rng.standard_normal(size=(n_paths, n_series)) @ chol.T)
    q_levels = np.asarray(q_levels, dtype=float)
    paths = np.empty((n_paths, horizon, n_series), dtype=float)
    for s in range(n_series):
        for t in range(horizon):
            paths[:, t, s] = np.interp(u[:, s], q_levels, quantile_values[s, t, :])
    return paths


class _Endpoint(Protocol):
    """Structural type for the injected AutoGluon endpoint."""
    def predict(self, data: pd.DataFrame, target: str, id_column: str,
                timestamp_column: str, prediction_length: int,
                known_covariates: Optional[pd.DataFrame] = ...) -> pd.DataFrame: ...


class Chronos2Client:
    """Wrapper around a Chronos-2 endpoint deployed via AutoGluon Cloud.

    Builds the long-format request frame, calls the injected endpoint, then
    reconstructs joint sample paths client-side (the endpoint returns
    per-series quantiles, not paths). The endpoint is injected so this module
    never imports `autogluon-cloud`.
    """

    def __init__(
        self,
        endpoint: _Endpoint,
        max_retries: int = 2,
        retry_sleep: float = 1.0,
    ) -> None:
        self.endpoint = endpoint
        self.max_retries = max_retries
        self.retry_sleep = retry_sleep

    def predict(
        self,
        context: pd.DataFrame,
        horizon: int,
        n_samples: int,
        covariates: Optional[pd.DataFrame] = None,
        conditioning: Optional[Conditioning] = None,
        seed: int = 0,
    ) -> np.ndarray:
        data, known = build_request_frame(context, horizon, covariates, conditioning)
        series = list(context.columns)
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                frame = self.endpoint.predict(
                    data=data, target="target", id_column="item_id",
                    timestamp_column="timestamp", prediction_length=horizon,
                    known_covariates=known,
                )
                q_levels, Q = decode_response(frame, series=series)
                R = lookback_correlation(context)
                return reconstruct_paths(
                    np.asarray(q_levels, dtype=float), Q, R,
                    n_paths=n_samples, seed=seed,
                )
            except Exception as e:  # endpoint/network error
                last_err = e
                if attempt < self.max_retries:
                    time.sleep(self.retry_sleep)
                    continue
                raise
        # unreachable, but keeps type-checkers happy:
        raise RuntimeError("retry loop exited without return") from last_err
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/models/test_chronos2_client_invoke.py -v
```
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/models/chronos2_client.py tests/models/test_chronos2_client_invoke.py
git commit -m "feat(chronos2): Chronos2Client reconstructs joint paths from quantiles

Endpoint returns per-series quantiles; reconstruct (n_paths, horizon,
n_series) joint paths via inverse-CDF + a lookback Gaussian copula. Retries
on transient SageMaker errors.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 13: `simulate_chronos2` returning a PathSet

**Files:**
- Modify: `src/chronos2_demo/models/chronos2_client.py` (append `simulate_chronos2`)
- Create: `tests/models/test_simulate_chronos2.py`

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np
import pandas as pd
from chronos2_demo.models import chronos2_client as c2
from chronos2_demo.types import PathSet


def _panel():
    idx = pd.bdate_range("2022-01-03", periods=120)
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        np.exp(rng.normal(0, 0.01, size=(120, 3)).cumsum(axis=0)),
        index=idx, columns=["A", "B", "C"],
    )


class _FakeEndpoint:
    """Returns a long-format quantile frame for the requested items/horizon."""
    def predict(self, data, target, id_column, timestamp_column,
                prediction_length, known_covariates=None):
        items = list(dict.fromkeys(data[id_column]))
        future = pd.bdate_range("2022-07-01", periods=prediction_length)
        rows = []
        for item in items:
            for t in range(prediction_length):
                row = {id_column: item, timestamp_column: future[t], "mean": 1.0}
                for ql in c2.Q_LEVELS:
                    row[str(ql)] = 1.0 + (ql - 0.5) * 0.1
                rows.append(row)
        return pd.DataFrame(rows)


def test_simulate_chronos2_returns_pathset_with_correct_metadata():
    client = c2.Chronos2Client(endpoint=_FakeEndpoint())
    panel = _panel()
    ps = c2.simulate_chronos2(client, panel, as_of="2022-06-01",
                              horizon=30, n_paths=100)
    assert isinstance(ps, PathSet)
    assert ps.source == "chronos2"
    assert ps.paths.shape == (100, 30, 3)
    assert ps.series == ["A", "B", "C"]
    assert np.isclose(ps.weights.sum(), 1.0)


def test_simulate_chronos2_marks_conditional_source_when_provided():
    client = c2.Chronos2Client(endpoint=_FakeEndpoint())
    panel = _panel()
    cond = c2.Conditioning(series_shifts={"A": 0.1}, n_anchor_days=5)
    ps = c2.simulate_chronos2(client, panel, as_of="2022-06-01",
                              horizon=10, n_paths=50, conditioning=cond)
    assert ps.source == "chronos2_conditional"
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/models/test_simulate_chronos2.py -v
```

- [ ] **Step 3: Append to `src/chronos2_demo/models/chronos2_client.py`**

```python
from chronos2_demo.types import PathSet


def simulate_chronos2(
    client: Chronos2Client,
    panel: pd.DataFrame,
    as_of: str,
    horizon: int,
    n_paths: int,
    lookback_days: int = 504,
    covariates: Optional[pd.DataFrame] = None,
    conditioning: Optional[Conditioning] = None,
    seed: int = 0,
) -> PathSet:
    """Slice the lookback window, call the endpoint, return a PathSet.

    Both unconditional and conditional calls flow through here. When
    `conditioning` is supplied, the source is "chronos2_conditional" so the
    augmentation layer can apply w_stress=1 by convention. `seed` makes the
    client-side path reconstruction deterministic.
    """
    as_of_ts = pd.Timestamp(as_of)
    history = panel.loc[:as_of_ts].tail(lookback_days)
    cov_slice = None
    if covariates is not None:
        cov_slice = covariates.loc[history.index]
    samples = client.predict(history, horizon=horizon, n_samples=n_paths,
                             covariates=cov_slice, conditioning=conditioning,
                             seed=seed)
    horizon_dates = pd.bdate_range(
        start=as_of_ts + pd.tseries.offsets.BDay(1), periods=horizon
    )
    weights = np.full(n_paths, 1.0 / n_paths)
    source: str = "chronos2_conditional" if conditioning is not None else "chronos2"
    return PathSet(
        paths=samples,
        weights=weights,
        series=list(panel.columns),
        dates=horizon_dates,
        source=source,  # type: ignore[arg-type]
    )
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/models/test_simulate_chronos2.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/models/chronos2_client.py tests/models/test_simulate_chronos2.py
git commit -m "feat(chronos2): add simulate_chronos2 returning PathSet

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 14: AutoGluon Cloud deploy/teardown + endpoint factory

**Files:**
- Create: `src/chronos2_demo/infra/__init__.py`
- Create: `src/chronos2_demo/infra/sagemaker_endpoint.py`
- Create: `scripts/deploy_chronos2_endpoint.py`
- Create: `tests/infra/__init__.py`
- Create: `tests/infra/test_sagemaker_endpoint.py`

Deploys the real `amazon/chronos-2` model via **AutoGluon Cloud** (`TimeSeriesFoundationModel(model_id="chronos-2")`), defaulting to a **serverless** endpoint. The pure config-builder and the deploy/teardown/`open_endpoint` orchestration accept **injected `model_factory` / `endpoint_factory`** so name+mode shaping is tested without importing `autogluon-cloud` or calling AWS. The real factories (which import `autogluon.cloud`) are only resolved on the live path — keeping the test suite and the core package import-light.

> **ARCC note:** SageMaker is an infra domain. Per `~/.claude/rules/arcc-governance.md` query `search_arcc` before this task; project memory records the ARCC MCP server is unavailable here, so apply the documented fallback (least-privilege execution role, no inline secrets, model-cache S3 bucket scoped to the project) and note ARCC was not queried.

- [ ] **Step 1: Write the failing tests**

```python
from unittest.mock import MagicMock
import pytest
from chronos2_demo.infra import sagemaker_endpoint as se


def test_deploy_kwargs_serverless_default():
    kw = se.build_deploy_kwargs()
    assert kw["inference_mode"] == "serverless"
    # serverless is CPU/auto-managed: no instance_type forced.
    assert "instance_type" not in kw


def test_deploy_kwargs_realtime_sets_instance_type():
    kw = se.build_deploy_kwargs(mode="realtime", instance_type="ml.g5.xlarge")
    assert kw["instance_type"] == "ml.g5.xlarge"
    assert "inference_mode" not in kw  # realtime is the SDK default mode


def test_deploy_demo_endpoint_serverless_caches_then_deploys():
    fake_endpoint = MagicMock()
    fake_endpoint.endpoint_name = "chronos2-demo-ep"
    cached = MagicMock()
    cached.deploy.return_value = fake_endpoint
    model = MagicMock()
    model.cache_model_artifact.return_value = cached
    factory = MagicMock(return_value=model)

    name = se.deploy_demo_endpoint(
        endpoint_name="chronos2-demo-ep",
        cache_uri="s3://bkt/fm-cache",
        model_factory=factory,
    )

    assert name == "chronos2-demo-ep"
    factory.assert_called_once_with(model_id="chronos-2")
    model.cache_model_artifact.assert_called_once_with("s3://bkt/fm-cache")
    assert cached.deploy.call_args.kwargs["inference_mode"] == "serverless"


def test_deploy_demo_endpoint_realtime_skips_cache():
    fake_endpoint = MagicMock()
    fake_endpoint.endpoint_name = "chronos2-demo-ep"
    model = MagicMock()
    model.deploy.return_value = fake_endpoint
    factory = MagicMock(return_value=model)

    name = se.deploy_demo_endpoint(
        endpoint_name="chronos2-demo-ep", mode="realtime",
        instance_type="ml.g5.xlarge", model_factory=factory)

    assert name == "chronos2-demo-ep"
    model.cache_model_artifact.assert_not_called()
    assert model.deploy.call_args.kwargs["instance_type"] == "ml.g5.xlarge"


def test_delete_demo_endpoint_calls_endpoint_delete():
    ep = MagicMock()
    se.delete_demo_endpoint(endpoint_name="chronos2-demo-ep",
                            endpoint_factory=lambda endpoint_name: ep)
    ep.delete_endpoint.assert_called_once()


def test_open_endpoint_attaches_by_name():
    ep = MagicMock()
    factory = MagicMock(return_value=ep)
    got = se.open_endpoint("chronos2-demo-ep", endpoint_factory=factory)
    assert got is ep
    factory.assert_called_once_with(endpoint_name="chronos2-demo-ep")
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/infra/test_sagemaker_endpoint.py -v
```

- [ ] **Step 3: Implement files**

`src/chronos2_demo/infra/__init__.py`: empty.

`tests/infra/__init__.py`: empty.

`src/chronos2_demo/infra/sagemaker_endpoint.py`:
```python
"""Chronos-2 deploy/teardown via AutoGluon Cloud.

The real amazon/chronos-2 model is deployed with
autogluon.cloud.TimeSeriesFoundationModel(model_id="chronos-2"). Serverless is
the demo default (CPU, scales to zero between demos). All AutoGluon-touching
calls go through injected factories so the config/orchestration shaping is
testable without importing autogluon-cloud or calling AWS. The real factories
(which import autogluon.cloud) are resolved only on the live path.
"""
from __future__ import annotations
from typing import Any, Callable, Optional

DEFAULT_MODEL_ID = "chronos-2"
DEFAULT_INSTANCE_TYPE = "ml.g5.xlarge"   # used only for mode="realtime"
DEFAULT_ENDPOINT_NAME = "chronos2-demo-ep"
DEFAULT_MODE = "serverless"


def build_deploy_kwargs(
    mode: str = DEFAULT_MODE,
    instance_type: str = DEFAULT_INSTANCE_TYPE,
) -> dict[str, Any]:
    """Shape the kwargs passed to AutoGluon's deploy() for the given mode."""
    if mode == "serverless":
        return {"inference_mode": "serverless"}
    if mode == "realtime":
        return {"instance_type": instance_type}
    raise ValueError(f"unknown mode {mode!r} (expected 'serverless' or 'realtime')")


def _default_model_factory(**kwargs: Any) -> Any:  # pragma: no cover - real path
    from autogluon.cloud import TimeSeriesFoundationModel
    return TimeSeriesFoundationModel(**kwargs)


def _default_endpoint_factory(**kwargs: Any) -> Any:  # pragma: no cover - real path
    from autogluon.cloud import TimeSeriesEndpoint
    return TimeSeriesEndpoint(**kwargs)


def deploy_demo_endpoint(
    endpoint_name: str = DEFAULT_ENDPOINT_NAME,
    mode: str = DEFAULT_MODE,
    instance_type: str = DEFAULT_INSTANCE_TYPE,
    cache_uri: Optional[str] = None,
    model_factory: Optional[Callable[..., Any]] = None,
) -> str:
    """Deploy the Chronos-2 endpoint via AutoGluon Cloud; return its name.

    Serverless requires the artifact be pre-cached to S3 (cache_uri); realtime
    deploys the model directly on a GPU instance. `model_factory` is injected
    in tests; defaults to autogluon.cloud.TimeSeriesFoundationModel.
    """
    model_factory = model_factory or _default_model_factory
    model = model_factory(model_id=DEFAULT_MODEL_ID)
    deploy_kwargs = build_deploy_kwargs(mode=mode, instance_type=instance_type)
    if mode == "serverless":
        target = model.cache_model_artifact(cache_uri)
    else:
        target = model
    endpoint = target.deploy(endpoint_name=endpoint_name, **deploy_kwargs)
    return endpoint.endpoint_name


def delete_demo_endpoint(
    endpoint_name: str = DEFAULT_ENDPOINT_NAME,
    endpoint_factory: Optional[Callable[..., Any]] = None,
) -> None:
    """Attach to the named endpoint and delete it."""
    endpoint_factory = endpoint_factory or (
        lambda endpoint_name: _default_endpoint_factory(endpoint_name=endpoint_name)
    )
    endpoint = endpoint_factory(endpoint_name=endpoint_name)
    endpoint.delete_endpoint()


def open_endpoint(
    endpoint_name: str = DEFAULT_ENDPOINT_NAME,
    endpoint_factory: Optional[Callable[..., Any]] = None,
) -> Any:
    """Return a live AutoGluon endpoint handle for an existing endpoint.

    This is the single place the Chronos2Client's injected `endpoint` comes
    from in production (deploy script + Fargate run_chronos2 task). It exposes
    `.predict(data, target, id_column, timestamp_column, prediction_length,
    known_covariates)`.
    """
    endpoint_factory = endpoint_factory or _default_endpoint_factory
    return endpoint_factory(endpoint_name=endpoint_name)
```

`scripts/deploy_chronos2_endpoint.py`:
```python
"""Deploy or tear down the Chronos-2 endpoint via AutoGluon Cloud.

Requires the `deploy` extra: pip install -e ".[deploy]".

Usage:
  python scripts/deploy_chronos2_endpoint.py --action deploy \\
      --cache-uri s3://YOUR-BUCKET/fm-cache
  python scripts/deploy_chronos2_endpoint.py --action deploy --mode realtime
  python scripts/deploy_chronos2_endpoint.py --action teardown
"""
from __future__ import annotations
import argparse
import sys

from chronos2_demo.infra import sagemaker_endpoint as se


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--action", choices=["deploy", "teardown"], required=True)
    p.add_argument("--endpoint-name", default=se.DEFAULT_ENDPOINT_NAME)
    p.add_argument("--mode", choices=["serverless", "realtime"], default=se.DEFAULT_MODE)
    p.add_argument("--instance-type", default=se.DEFAULT_INSTANCE_TYPE,
                   help="GPU instance for --mode realtime")
    p.add_argument("--cache-uri", default=None,
                   help="S3 URI for the cached model artifact (required for serverless)")
    args = p.parse_args()
    if args.action == "deploy":
        if args.mode == "serverless" and not args.cache_uri:
            p.error("--cache-uri is required for serverless deploys")
        name = se.deploy_demo_endpoint(
            endpoint_name=args.endpoint_name,
            mode=args.mode,
            instance_type=args.instance_type,
            cache_uri=args.cache_uri,
        )
        print(f"deployed endpoint: {name}")
    else:
        se.delete_demo_endpoint(endpoint_name=args.endpoint_name)
        print(f"deleted endpoint: {args.endpoint_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/infra/test_sagemaker_endpoint.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/infra/ tests/infra/ scripts/deploy_chronos2_endpoint.py
git commit -m "feat(infra): deploy Chronos-2 via AutoGluon Cloud (serverless default)

Replace the un-deployable create_endpoint stub with an AutoGluon Cloud
deployer exposing deploy_demo_endpoint()/delete_demo_endpoint()/open_endpoint().
Serverless default (scales to zero between demos); realtime GPU optional. All
autogluon-cloud imports behind injected factories so core + tests stay light.
ARCC not queried (MCP unavailable); applied least-privilege fallback.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

> _Continue with `2026-05-22-plan-a-quant-pipeline-part-2c.md` (Stage 4 — Augmentation, Tasks 15–17)._
