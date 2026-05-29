import json
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


def test_encode_request_round_trips():
    panel = _panel()
    body = c2.encode_request(panel, horizon=10, n_samples=5,
                             covariates=None, conditioning=None)
    payload = json.loads(body)
    assert payload["horizon"] == 10
    assert payload["n_samples"] == 5
    assert payload["covariates"] is None
    assert payload["conditioning"] is None
    assert np.array(payload["context"]).shape == (20, 3)


def test_encode_request_includes_covariates_when_provided():
    panel = _panel()
    cov = pd.DataFrame(np.zeros((20, 2)) + 0.5, index=panel.index,
                       columns=["VIX", "MOVE"])
    body = c2.encode_request(panel, horizon=10, n_samples=5,
                             covariates=cov, conditioning=None)
    payload = json.loads(body)
    assert np.array(payload["covariates"]).shape == (20, 2)


def test_encode_request_rejects_misaligned_covariates():
    panel = _panel()
    cov = pd.DataFrame(np.zeros((19, 2)), index=panel.index[:19],
                       columns=["VIX", "MOVE"])
    with pytest.raises(ValueError, match="align"):
        c2.encode_request(panel, horizon=10, n_samples=5,
                          covariates=cov, conditioning=None)


def test_decode_response_returns_samples_array():
    samples = (np.random.default_rng(0).normal(size=(7, 30, 3)) + 100).tolist()
    body = json.dumps({"samples": samples})
    out = c2.decode_response(body)
    assert out.shape == (7, 30, 3)


def test_decode_response_rejects_missing_samples():
    with pytest.raises(KeyError):
        c2.decode_response(json.dumps({"foo": []}))
