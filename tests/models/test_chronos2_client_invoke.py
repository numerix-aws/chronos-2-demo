import json
from unittest.mock import MagicMock
import numpy as np
import pandas as pd
import pytest
from chronos2_demo.models import chronos2_client as c2


def _panel():
    idx = pd.bdate_range("2022-01-03", periods=10)
    return pd.DataFrame(np.ones((10, 3)), index=idx, columns=["A", "B", "C"])


def _mock_runtime(samples_shape, side_effects=None):
    rt = MagicMock()
    samples = np.ones(samples_shape).tolist()
    body = MagicMock()
    body.read.return_value = json.dumps({"samples": samples}).encode("utf-8")
    if side_effects is None:
        rt.invoke_endpoint.return_value = {"Body": body}
    else:
        rt.invoke_endpoint.side_effect = side_effects + [{"Body": body}]
    return rt


def test_client_invokes_endpoint_and_returns_array():
    rt = _mock_runtime((4, 30, 3))
    client = c2.Chronos2Client(endpoint_name="ep", runtime=rt)
    out = client.predict(_panel(), horizon=30, n_samples=4)
    assert out.shape == (4, 30, 3)
    rt.invoke_endpoint.assert_called_once()
    kwargs = rt.invoke_endpoint.call_args.kwargs
    assert kwargs["EndpointName"] == "ep"
    assert kwargs["ContentType"] == "application/json"


def test_client_retries_on_transient_error():
    from botocore.exceptions import ClientError
    err = ClientError({"Error": {"Code": "ModelError", "Message": "transient"}},
                      "InvokeEndpoint")
    rt = _mock_runtime((2, 5, 3), side_effects=[err])
    client = c2.Chronos2Client(endpoint_name="ep", runtime=rt, max_retries=2,
                               retry_sleep=0.0)
    out = client.predict(_panel(), horizon=5, n_samples=2)
    assert out.shape == (2, 5, 3)
    assert rt.invoke_endpoint.call_count == 2


def test_client_gives_up_after_max_retries():
    from botocore.exceptions import ClientError
    err = ClientError({"Error": {"Code": "ModelError", "Message": "no"}},
                      "InvokeEndpoint")
    rt = MagicMock()
    rt.invoke_endpoint.side_effect = err
    client = c2.Chronos2Client(endpoint_name="ep", runtime=rt, max_retries=2,
                               retry_sleep=0.0)
    with pytest.raises(ClientError):
        client.predict(_panel(), horizon=5, n_samples=2)
    assert rt.invoke_endpoint.call_count == 3  # initial + 2 retries
