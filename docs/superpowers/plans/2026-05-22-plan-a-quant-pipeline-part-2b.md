# Plan A — Part 2b: Stage 3 — Chronos-2 Client & SageMaker Deployment

> **Continuation of** `2026-05-22-plan-a-quant-pipeline-part-2a.md`. Tasks 11–14.

---

## Stage 3 — Chronos-2 client & SageMaker deployment

The Chronos-2 client is a thin wrapper over a SageMaker real-time endpoint. Tests are hermetic — they mock the SageMaker runtime client. Real endpoint deployment lives in `scripts/deploy_chronos2_endpoint.py`.

**Endpoint contract (locked):**
- Request body (JSON): `{"context": [[...], [...], ...], "covariates": [...] | null, "conditioning": {...} | null, "horizon": int, "n_samples": int}`
- Response body (JSON): `{"samples": [[[...]]]}` — shape `(n_samples, horizon, n_series)` of absolute levels.

The wrapper handles JSON encoding, retries on transient SageMaker errors, and returns a `PathSet`.

### Task 11: Endpoint payload encoder + decoder

**Files:**
- Create: `src/chronos2_demo/models/chronos2_client.py` (encoder/decoder + dataclasses only)
- Create: `tests/models/test_chronos2_client_payload.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/models/test_chronos2_client_payload.py -v
```

- [ ] **Step 3: Implement `src/chronos2_demo/models/chronos2_client.py` (this task adds only encode/decode)**

```python
"""Client for the Chronos-2 SageMaker real-time endpoint.

Endpoint contract:
  Request:  {"context": [[...]], "covariates": [[...]] | null,
             "conditioning": {...} | null, "horizon": int, "n_samples": int}
  Response: {"samples": [[[...]]]}  shape (n_samples, horizon, n_series)

This file is split across Tasks 11-13. Task 11 adds encode/decode.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import json
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Conditioning:
    """User-supplied stress narrative passed as a prefix anchor.

    `series_shifts` is a per-series additive shift over the first
    `n_anchor_days` of the forecast horizon (in absolute level units).
    """
    series_shifts: dict[str, float]
    n_anchor_days: int

    def to_jsonable(self) -> dict[str, Any]:
        return {"series_shifts": dict(self.series_shifts),
                "n_anchor_days": int(self.n_anchor_days)}


def encode_request(
    context: pd.DataFrame,
    horizon: int,
    n_samples: int,
    covariates: pd.DataFrame | None,
    conditioning: Conditioning | None,
) -> str:
    if covariates is not None:
        if not context.index.equals(covariates.index):
            raise ValueError("covariates index must align with context index")
    payload = {
        "context": context.values.tolist(),
        "covariates": (covariates.values.tolist() if covariates is not None else None),
        "conditioning": (conditioning.to_jsonable() if conditioning is not None else None),
        "horizon": int(horizon),
        "n_samples": int(n_samples),
    }
    return json.dumps(payload)


def decode_response(body: str) -> np.ndarray:
    obj = json.loads(body)
    if "samples" not in obj:
        raise KeyError("response missing 'samples'")
    return np.asarray(obj["samples"], dtype=float)
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/models/test_chronos2_client_payload.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/models/chronos2_client.py tests/models/test_chronos2_client_payload.py
git commit -m "feat(chronos2): add request encoder + response decoder

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 12: Endpoint invocation with retries (mocked)

**Files:**
- Modify: `src/chronos2_demo/models/chronos2_client.py` (append `Chronos2Client`)
- Create: `tests/models/test_chronos2_client_invoke.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/models/test_chronos2_client_invoke.py -v
```

- [ ] **Step 3: Append to `src/chronos2_demo/models/chronos2_client.py`**

```python
import time
from typing import Optional


class Chronos2Client:
    """Thin wrapper around a SageMaker real-time endpoint."""

    def __init__(
        self,
        endpoint_name: str,
        runtime: Any,
        max_retries: int = 2,
        retry_sleep: float = 1.0,
    ) -> None:
        self.endpoint_name = endpoint_name
        self.runtime = runtime
        self.max_retries = max_retries
        self.retry_sleep = retry_sleep

    def predict(
        self,
        context: pd.DataFrame,
        horizon: int,
        n_samples: int,
        covariates: Optional[pd.DataFrame] = None,
        conditioning: Optional[Conditioning] = None,
    ) -> np.ndarray:
        body = encode_request(context, horizon, n_samples, covariates, conditioning)
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.runtime.invoke_endpoint(
                    EndpointName=self.endpoint_name,
                    ContentType="application/json",
                    Accept="application/json",
                    Body=body,
                )
                return decode_response(resp["Body"].read().decode("utf-8"))
            except Exception as e:  # botocore ClientError, network, etc.
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
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/models/chronos2_client.py tests/models/test_chronos2_client_invoke.py
git commit -m "feat(chronos2): add Chronos2Client with retries

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 13: `simulate_chronos2` returning a PathSet

**Files:**
- Modify: `src/chronos2_demo/models/chronos2_client.py` (append `simulate_chronos2`)
- Create: `tests/models/test_simulate_chronos2.py`

- [ ] **Step 1: Write the failing tests**

```python
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
) -> PathSet:
    """Slice the lookback window, call the endpoint, return a PathSet.

    Both unconditional and conditional calls flow through here. When
    `conditioning` is supplied, the source is "chronos2_conditional" so the
    augmentation layer can apply w_stress=1 by convention.
    """
    as_of_ts = pd.Timestamp(as_of)
    history = panel.loc[:as_of_ts].tail(lookback_days)
    cov_slice = None
    if covariates is not None:
        cov_slice = covariates.loc[history.index]
    samples = client.predict(history, horizon=horizon, n_samples=n_paths,
                             covariates=cov_slice, conditioning=conditioning)
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

### Task 14: SageMaker endpoint deploy/teardown script

**Files:**
- Create: `src/chronos2_demo/infra/__init__.py`
- Create: `src/chronos2_demo/infra/sagemaker_endpoint.py`
- Create: `scripts/deploy_chronos2_endpoint.py`
- Create: `tests/infra/__init__.py`
- Create: `tests/infra/test_sagemaker_endpoint.py`

The deployer is mostly orchestration — tests cover the parameter-shaping and tag-construction logic. Actual deployment is exercised manually.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from chronos2_demo.infra import sagemaker_endpoint as se


def test_endpoint_config_defaults_for_demo():
    cfg = se.build_endpoint_config(model_name="chronos2-demo")
    assert cfg["instance_type"].startswith("ml.g5.")
    assert cfg["initial_instance_count"] == 1
    assert "Project" in dict(cfg["tags"])
    assert dict(cfg["tags"])["Project"] == "chronos2-demo"


def test_endpoint_config_overrides_apply():
    cfg = se.build_endpoint_config(
        model_name="chronos2-demo",
        instance_type="ml.g5.2xlarge",
        extra_tags={"Owner": "muffadal"},
    )
    assert cfg["instance_type"] == "ml.g5.2xlarge"
    assert dict(cfg["tags"])["Owner"] == "muffadal"
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
"""SageMaker real-time endpoint orchestration for Chronos-2.

Deploy + teardown is exercised manually via scripts/deploy_chronos2_endpoint.py.
The pure config builders here are unit-tested.
"""
from __future__ import annotations
from typing import Any


def build_endpoint_config(
    model_name: str,
    instance_type: str = "ml.g5.xlarge",
    initial_instance_count: int = 1,
    extra_tags: dict[str, str] | None = None,
) -> dict[str, Any]:
    tags = [{"Key": "Project", "Value": "chronos2-demo"},
            {"Key": "ModelName", "Value": model_name}]
    if extra_tags:
        tags += [{"Key": k, "Value": v} for k, v in extra_tags.items()]
    return {
        "model_name": model_name,
        "instance_type": instance_type,
        "initial_instance_count": initial_instance_count,
        "tags": [(t["Key"], t["Value"]) for t in tags],
    }
```

`scripts/deploy_chronos2_endpoint.py`:
```python
"""Deploy or tear down the Chronos-2 SageMaker endpoint.

Usage:
  python scripts/deploy_chronos2_endpoint.py --action deploy --model-name chronos2-demo
  python scripts/deploy_chronos2_endpoint.py --action teardown --endpoint-name chronos2-demo-ep
"""
from __future__ import annotations
import argparse
import sys

import boto3

from chronos2_demo.infra import sagemaker_endpoint as se


def deploy(args: argparse.Namespace) -> int:
    cfg = se.build_endpoint_config(
        model_name=args.model_name,
        instance_type=args.instance_type,
    )
    sm = boto3.client("sagemaker", region_name=args.region)
    endpoint_name = f"{args.model_name}-ep"
    cfg_name = f"{args.model_name}-cfg"
    sm.create_endpoint_config(
        EndpointConfigName=cfg_name,
        ProductionVariants=[{
            "VariantName": "AllTraffic",
            "ModelName": cfg["model_name"],
            "InitialInstanceCount": cfg["initial_instance_count"],
            "InstanceType": cfg["instance_type"],
        }],
        Tags=[{"Key": k, "Value": v} for k, v in cfg["tags"]],
    )
    sm.create_endpoint(EndpointName=endpoint_name, EndpointConfigName=cfg_name,
                       Tags=[{"Key": k, "Value": v} for k, v in cfg["tags"]])
    print(f"creating endpoint: {endpoint_name}")
    return 0


def teardown(args: argparse.Namespace) -> int:
    sm = boto3.client("sagemaker", region_name=args.region)
    sm.delete_endpoint(EndpointName=args.endpoint_name)
    print(f"deleted endpoint: {args.endpoint_name}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--action", choices=["deploy", "teardown"], required=True)
    p.add_argument("--model-name", default="chronos2-demo")
    p.add_argument("--endpoint-name", default="chronos2-demo-ep")
    p.add_argument("--instance-type", default="ml.g5.xlarge")
    p.add_argument("--region", default="us-east-1")
    args = p.parse_args()
    if args.action == "deploy":
        return deploy(args)
    return teardown(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/infra/test_sagemaker_endpoint.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/infra/ tests/infra/ scripts/deploy_chronos2_endpoint.py
git commit -m "feat(infra): add SageMaker endpoint deploy/teardown helpers

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

> _Continue with `2026-05-22-plan-a-quant-pipeline-part-2c.md` (Stage 4 — Augmentation, Tasks 15–17)._
