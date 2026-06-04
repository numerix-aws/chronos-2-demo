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
