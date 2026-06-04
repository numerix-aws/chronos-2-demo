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
