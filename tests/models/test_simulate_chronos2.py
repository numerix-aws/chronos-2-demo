import json
from unittest.mock import MagicMock
import numpy as np
import pandas as pd
from chronos2_demo.models import chronos2_client as c2
from chronos2_demo.types import PathSet


def _panel():
    idx = pd.bdate_range("2022-01-03", periods=20)
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        rng.normal(0, 0.01, size=(20, 3)).cumsum(axis=0) + 1.0,
        index=idx, columns=["A", "B", "C"],
    )


def _client_returning(samples: np.ndarray):
    rt = MagicMock()
    body = MagicMock()
    body.read.return_value = json.dumps({"samples": samples.tolist()}).encode("utf-8")
    rt.invoke_endpoint.return_value = {"Body": body}
    return c2.Chronos2Client(endpoint_name="ep", runtime=rt)


def test_simulate_chronos2_returns_pathset_with_correct_metadata():
    samples = np.full((100, 30, 3), 1.5)
    client = _client_returning(samples)
    panel = _panel()
    ps = c2.simulate_chronos2(client, panel, as_of="2022-01-28",
                              horizon=30, n_paths=100)
    assert isinstance(ps, PathSet)
    assert ps.source == "chronos2"
    assert ps.paths.shape == (100, 30, 3)
    assert ps.series == ["A", "B", "C"]
    assert np.isclose(ps.weights.sum(), 1.0)


def test_simulate_chronos2_marks_conditional_source_when_provided():
    samples = np.full((50, 10, 3), 1.0)
    client = _client_returning(samples)
    panel = _panel()
    cond = c2.Conditioning(series_shifts={"A": 0.1}, n_anchor_days=5)
    ps = c2.simulate_chronos2(client, panel, as_of="2022-01-28",
                              horizon=10, n_paths=50, conditioning=cond)
    assert ps.source == "chronos2_conditional"
