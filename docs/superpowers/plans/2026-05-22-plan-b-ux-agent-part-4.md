# Plan B — Part 4: Stages 3-4 — Fargate Baseline MC + Chronos-2, Tools Stack

> **Continuation of** `2026-05-22-plan-b-ux-agent-part-3.md`. Tasks 10-13 (incl. async-Fargate launcher+poll pairs: 11a/11b for `run_baseline_mc`, 11c/11d for `run_chronos2`).

---

## Stage 3 — Fargate baseline MC + Chronos-2

### Task 10: Fargate `baseline_mc` task — Dockerfile + entrypoint

**Files:**
- Create: `tools/fargate/baseline_mc/Dockerfile`
- Create: `tools/fargate/baseline_mc/entrypoint.py`
- Create: `tools/fargate/baseline_mc/requirements.txt`
- Create: `tools/tests/test_baseline_mc_entrypoint.py`

The baseline MC engine is CPU-heavy (large numpy work) and lives in
Plan A's `models.baseline_mc`. We package it into a Fargate container
with a thin entrypoint that reads task input from environment variables,
runs the engine, and uploads the resulting PathSet to S3. The agent's
tool dispatcher (Stage 4) starts the task via `ECS RunTask`.

- [ ] **Step 1: Write the failing entrypoint test**

`tools/tests/test_baseline_mc_entrypoint.py`:
```python
"""Test the entrypoint as a function: env vars in, S3 upload out."""
import io
import numpy as np
import pandas as pd
import pickle
import pytest
import sys
from pathlib import Path

# Treat the entrypoint script directory as importable.
ENTRY_DIR = Path(__file__).resolve().parents[1] / "fargate" / "baseline_mc"
sys.path.insert(0, str(ENTRY_DIR))


def _seed_panel(s3_client, bucket="test-data"):
    from tools.lambda_.shared import s3_io
    rng = np.random.default_rng(0)
    panel = pd.DataFrame(
        rng.normal(0, 0.005, size=(60, 5)).cumsum(axis=0),
        index=pd.bdate_range("2022-04-01", periods=60),
        columns=["USDEUR", "USDJPY", "USD_2Y", "USD_5Y", "USD_10Y"],
    )
    s3_io.upload_parquet(panel, bucket=bucket, key="lookback.parquet")


def test_entrypoint_uploads_pathset_to_s3(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("PANEL_URI", "s3://test-data/lookback.parquet")
    monkeypatch.setenv("AS_OF", "2022-06-23")  # last business day of the 60-day panel
    monkeypatch.setenv("HORIZON", "21")
    monkeypatch.setenv("N_PATHS", "200")
    monkeypatch.setenv("N_COMPONENTS", "3")
    monkeypatch.setenv("OUTPUT_KEY", "sessions/abc/baseline.pkl")
    monkeypatch.setenv("SEED", "42")
    _seed_panel(s3)

    import importlib
    entrypoint = importlib.import_module("entrypoint")
    importlib.reload(entrypoint)
    out_uri = entrypoint.main()

    assert out_uri == "s3://test-data/sessions/abc/baseline.pkl"
    body = s3.get_object(Bucket="test-data", Key="sessions/abc/baseline.pkl")["Body"].read()
    ps = pickle.load(io.BytesIO(body))
    assert ps.paths.shape == (200, 21, 5)
    assert ps.source == "parametric"


def test_entrypoint_validates_horizon(monkeypatch, s3):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("PANEL_URI", "s3://test-data/lookback.parquet")
    monkeypatch.setenv("AS_OF", "2022-06-23")
    monkeypatch.setenv("HORIZON", "0")
    monkeypatch.setenv("N_PATHS", "200")
    monkeypatch.setenv("N_COMPONENTS", "3")
    monkeypatch.setenv("OUTPUT_KEY", "x.pkl")
    monkeypatch.setenv("SEED", "42")
    _seed_panel(s3)

    import importlib
    entrypoint = importlib.import_module("entrypoint")
    importlib.reload(entrypoint)
    with pytest.raises(ValueError, match="HORIZON"):
        entrypoint.main()
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tools/tests/test_baseline_mc_entrypoint.py -v
```

Expected: FAIL — `entrypoint` module missing.

- [ ] **Step 3: Implement `tools/fargate/baseline_mc/entrypoint.py`**

```python
"""Fargate entrypoint for the baseline MC task.

Env vars:
  DATA_BUCKET, PANEL_URI, AS_OF, HORIZON, N_PATHS, N_COMPONENTS, OUTPUT_KEY, SEED
Output: S3 URI (pickle) of a PathSet.

`simulate_baseline` (Plan A) fits PCA + factor dynamics on the panel history up
to `AS_OF` and returns a fully-formed PathSet (source="parametric"), so the
entrypoint just validates, runs, and uploads.
"""
from __future__ import annotations
import io
import os
import pickle
import sys

import boto3

from chronos2_demo.models import baseline_mc
from tools.lambda_.shared import s3_io


def main() -> str:
    bucket = os.environ["DATA_BUCKET"]
    panel_uri = os.environ["PANEL_URI"]
    as_of = os.environ["AS_OF"]
    horizon = int(os.environ["HORIZON"])
    n_paths = int(os.environ["N_PATHS"])
    n_components = int(os.environ.get("N_COMPONENTS", "3"))
    output_key = os.environ["OUTPUT_KEY"]
    seed = int(os.environ.get("SEED", "0"))

    if horizon <= 0 or horizon > 1000:
        raise ValueError(f"HORIZON must be in (0, 1000], got {horizon}")
    if n_paths <= 0 or n_paths > 50_000:
        raise ValueError(f"N_PATHS must be in (0, 50000], got {n_paths}")

    panel = s3_io.download_parquet(panel_uri)
    ps = baseline_mc.simulate_baseline(
        panel=panel,
        as_of=as_of,
        horizon=horizon,
        n_paths=n_paths,
        n_components=n_components,
        seed=seed,
    )
    buf = io.BytesIO()
    pickle.dump(ps, buf)
    boto3.client("s3").put_object(Bucket=bucket, Key=output_key, Body=buf.getvalue())
    uri = f"s3://{bucket}/{output_key}"
    print(uri, file=sys.stdout)
    return uri


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Create `tools/fargate/baseline_mc/requirements.txt`**

```
numpy>=1.26
scipy>=1.12
pandas>=2.2
scikit-learn>=1.4
pyarrow>=15.0
boto3>=1.34
```

- [ ] **Step 5: Create `tools/fargate/baseline_mc/Dockerfile`**

```dockerfile
FROM public.ecr.aws/docker/library/python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY tools/fargate/baseline_mc/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# chronos2_demo source + the lambda shared shim
COPY src/chronos2_demo /app/chronos2_demo
COPY tools/lambda/shared /app/tools/lambda_/shared
COPY tools/__init__.py /app/tools/__init__.py
RUN mkdir -p /app/tools/lambda_ && touch /app/tools/lambda_/__init__.py

COPY tools/fargate/baseline_mc/entrypoint.py /app/entrypoint.py

ENV PYTHONPATH=/app

CMD ["python", "/app/entrypoint.py"]
```

- [ ] **Step 6: Run tests, confirm pass**

```bash
pytest tools/tests/test_baseline_mc_entrypoint.py -v
```

Expected: 2 passed.

- [ ] **Step 7: Smoke-build the image (optional but recommended)**

```bash
docker build -f tools/fargate/baseline_mc/Dockerfile -t chronos2-demo-baseline-mc .
```

Expected: image built. Skip if Docker unavailable; CDK build will catch it later.

- [ ] **Step 8: Commit**

```bash
git add tools/fargate/baseline_mc/ tools/tests/test_baseline_mc_entrypoint.py
git commit -m "feat(tools): Fargate baseline MC container + entrypoint

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 11: Fargate `run_chronos2` task — Dockerfile + entrypoint

**Files:**
- Create: `tools/fargate/run_chronos2/Dockerfile`
- Create: `tools/fargate/run_chronos2/entrypoint.py`
- Create: `tools/fargate/run_chronos2/requirements.txt`
- Create: `tools/tests/test_run_chronos2_entrypoint.py`

**Why Fargate, not Lambda.** Chronos-2 is deployed via **AutoGluon Cloud** (Plan A, revised), so the only place that opens a live endpoint imports `autogluon.cloud` — far too heavy for a Lambda layer. We mirror the baseline-MC pattern (Task 10): a Fargate container does the work, launched async by a thin Lambda (Task 11c) and polled by `check_chronos2` (Task 11d). The container bundles `autogluon-cloud`; the Lambdas stay thin (`boto3` only).

The entrypoint mirrors `tools/fargate/baseline_mc/entrypoint.py`: validate env, open the endpoint, run Plan A's `simulate_chronos2`, upload the PathSet pickle. `open_endpoint` (Plan A `infra.sagemaker_endpoint`) is the single seam that imports AutoGluon; the test patches it so the suite stays hermetic.

> **Contract note (Plan A alignment):** the AutoGluon endpoint returns **per-series quantiles**, not sample paths. `simulate_chronos2` reconstructs the joint `(n_paths, horizon, n_series)` PathSet client-side (Gaussian copula over the shared lookback). The entrypoint is a thin driver of that call.

- [ ] **Step 1: Write the failing test**

`tools/tests/test_run_chronos2_entrypoint.py`:
```python
"""Test the run_chronos2 entrypoint as a function: env vars in, S3 upload out.

Mirrors test_baseline_mc_entrypoint.py: insert the entrypoint dir on sys.path
and import it as the top-level `entrypoint` module. We pop any cached `entrypoint`
first so this file and the baseline entrypoint test don't collide in one session.
"""
import importlib
import io
import sys
import numpy as np
import pandas as pd
import pickle
import pytest
from pathlib import Path
from unittest.mock import patch
from chronos2_demo.types import PathSet

ENTRY_DIR = Path(__file__).resolve().parents[1] / "fargate" / "run_chronos2"


def _seed_panel(s3_client, bucket="test-data", key="lb.parquet"):
    from tools.lambda_.shared import s3_io
    panel = pd.DataFrame(
        np.random.default_rng(0).normal(0, 0.005, size=(60, 3)).cumsum(axis=0),
        index=pd.bdate_range("2022-04-01", periods=60),
        columns=["USDEUR", "USDJPY", "USD_5Y"],
    )
    s3_io.upload_parquet(panel, bucket=bucket, key=key)


def _load_entrypoint():
    sys.path.insert(0, str(ENTRY_DIR))
    sys.modules.pop("entrypoint", None)
    import entrypoint
    return importlib.reload(entrypoint)


def test_entrypoint_runs_and_uploads_pathset(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("PANEL_URI", "s3://test-data/lb.parquet")
    monkeypatch.setenv("AS_OF", "2022-06-23")
    monkeypatch.setenv("HORIZON", "21")
    monkeypatch.setenv("N_PATHS", "50")
    monkeypatch.setenv("OUTPUT_KEY", "sessions/abc/chronos2.pkl")
    monkeypatch.setenv("CHRONOS2_ENDPOINT", "chronos2-demo-ep")
    _seed_panel(s3)

    fake_ps = PathSet(
        paths=np.zeros((50, 21, 3), dtype=float),
        weights=np.full(50, 1.0 / 50),
        series=["USDEUR", "USDJPY", "USD_5Y"],
        dates=pd.bdate_range("2022-06-24", periods=21),
        source="chronos2",
    )
    ep = _load_entrypoint()
    with patch.object(ep.sagemaker_endpoint, "open_endpoint", return_value=object()), \
         patch.object(ep.chronos2_client, "simulate_chronos2", return_value=fake_ps) as m:
        uri = ep.main()

    assert uri == "s3://test-data/sessions/abc/chronos2.pkl"
    m.assert_called_once()
    body = s3.get_object(Bucket="test-data", Key="sessions/abc/chronos2.pkl")["Body"].read()
    obj = pickle.load(io.BytesIO(body))
    assert obj.source == "chronos2"


def test_entrypoint_rejects_bad_horizon(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("PANEL_URI", "s3://test-data/lb.parquet")
    monkeypatch.setenv("AS_OF", "2022-06-23")
    monkeypatch.setenv("HORIZON", "0")
    monkeypatch.setenv("N_PATHS", "50")
    monkeypatch.setenv("OUTPUT_KEY", "sessions/abc/chronos2.pkl")
    monkeypatch.setenv("CHRONOS2_ENDPOINT", "ep")
    _seed_panel(s3)
    ep = _load_entrypoint()
    with pytest.raises(ValueError, match="HORIZON"):
        ep.main()
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tools/tests/test_run_chronos2_entrypoint.py -v
```

Expected: FAIL — module missing.

- [ ] **Step 3: Implement `tools/fargate/run_chronos2/entrypoint.py`**

```python
"""Fargate entrypoint for the run_chronos2 task.

Env vars:
  DATA_BUCKET, PANEL_URI, AS_OF, HORIZON, N_PATHS, OUTPUT_KEY,
  CHRONOS2_ENDPOINT, COVARIATES_URI?, SEED?
Output: S3 URI (pickle) of a PathSet.

Opens the AutoGluon Cloud endpoint (the single autogluon-cloud import lives in
`infra.sagemaker_endpoint.open_endpoint`), then runs Plan A's simulate_chronos2,
which reconstructs joint paths from the endpoint's per-series quantiles.
"""
from __future__ import annotations
import io
import os
import pickle
import sys

import boto3

from chronos2_demo.infra import sagemaker_endpoint
from chronos2_demo.models import chronos2_client
from tools.lambda_.shared import s3_io


def main() -> str:
    bucket = os.environ["DATA_BUCKET"]
    panel_uri = os.environ["PANEL_URI"]
    as_of = os.environ["AS_OF"]
    horizon = int(os.environ["HORIZON"])
    n_paths = int(os.environ["N_PATHS"])
    output_key = os.environ["OUTPUT_KEY"]
    endpoint_name = os.environ["CHRONOS2_ENDPOINT"]
    seed = int(os.environ.get("SEED", "0"))

    if horizon <= 0 or horizon > 1000:
        raise ValueError(f"HORIZON must be in (0, 1000], got {horizon}")
    if n_paths <= 0 or n_paths > 20_000:
        raise ValueError(f"N_PATHS must be in (0, 20000], got {n_paths}")

    panel = s3_io.download_parquet(panel_uri)
    covariates = None
    if os.environ.get("COVARIATES_URI"):
        covariates = s3_io.download_parquet(os.environ["COVARIATES_URI"])

    endpoint = sagemaker_endpoint.open_endpoint(endpoint_name)
    client = chronos2_client.Chronos2Client(endpoint=endpoint)
    ps = chronos2_client.simulate_chronos2(
        client,
        panel=panel,
        as_of=as_of,
        horizon=horizon,
        n_paths=n_paths,
        covariates=covariates,
        seed=seed,
    )

    buf = io.BytesIO()
    pickle.dump(ps, buf)
    boto3.client("s3").put_object(Bucket=bucket, Key=output_key, Body=buf.getvalue())
    uri = f"s3://{bucket}/{output_key}"
    print(uri, file=sys.stdout)
    return uri


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Create `tools/fargate/run_chronos2/requirements.txt`**

```text
# Plan A package (editable copy baked into the image) + the AutoGluon Cloud SDK.
# Heavy on purpose; this is why run_chronos2 is Fargate, not Lambda.
autogluon-cloud>=0.5.0
boto3>=1.34
pandas>=2.2
pyarrow>=15.0
```

- [ ] **Step 5: Create `tools/fargate/run_chronos2/Dockerfile`**

```dockerfile
FROM public.ecr.aws/docker/library/python:3.11-slim

WORKDIR /app
COPY tools/fargate/run_chronos2/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Plan A package + shared tool helpers.
COPY pyproject.toml /app/pyproject.toml
COPY src /app/src
RUN pip install --no-cache-dir -e .
COPY tools /app/tools

COPY tools/fargate/run_chronos2/entrypoint.py /app/entrypoint.py
ENV PYTHONPATH=/app
CMD ["python", "/app/entrypoint.py"]
```

- [ ] **Step 6: Run tests, confirm pass**

```bash
pytest tools/tests/test_run_chronos2_entrypoint.py -v
```
Expected: 2 passed.

- [ ] **Step 7: Verify the image builds**

```bash
docker build -f tools/fargate/run_chronos2/Dockerfile -t chronos2-demo-run-chronos2 .
```
Expected: build succeeds. (The AutoGluon install is large; first build is slow.)

- [ ] **Step 8: Commit**

```bash
git add tools/fargate/run_chronos2/ tools/tests/test_run_chronos2_entrypoint.py
git commit -m "feat(tools): Fargate run_chronos2 container (AutoGluon Cloud endpoint)

Move run_chronos2 off Lambda: the AutoGluon Cloud SDK is too heavy for a
Lambda layer, so the endpoint call runs in a Fargate container (mirrors the
baseline-MC pattern). Entrypoint opens the endpoint + runs simulate_chronos2.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 11a: `run_baseline_mc` launcher Lambda — start the Fargate task

**Files:**
- Create: `tools/lambda/run_baseline_mc/__init__.py` (empty)
- Create: `tools/lambda/run_baseline_mc/handler.py`
- Create: `tools/tests/test_run_baseline_mc.py`

The baseline MC engine is CPU-heavy and runs as the Fargate task from Task 10.
Because Fargate tasks take minutes, the agent **launches** the task here and
**polls** with `check_baseline_mc` (Task 11b) — the tool returns immediately
with a task handle and the S3 URI where the result *will* land. This is the
async beat the agent's system prompt narrates (Stage 5).

The handler computes a deterministic `OUTPUT_KEY`, calls `ECS RunTask` with the
container env overrides the Task 10 entrypoint reads, and returns
`{task_arn, paths_uri}`. Networking + cluster/task-def come from env vars set
by the tools stack (Task 13).

- [ ] **Step 1: Write the failing test**

`tools/tests/test_run_baseline_mc.py`:
```python
import boto3
import pytest
from moto import mock_aws

from tools.lambda_.run_baseline_mc import handler


@pytest.fixture
def ecs_env(aws_creds, monkeypatch):
    with mock_aws():
        # moto's ECS RunTask validates the awsvpc subnets + security groups
        # against the EC2 backend, so create real (mocked) ones.
        ec2 = boto3.client("ec2", region_name="us-east-1")
        vpc_id = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
        # moto's ECS RunTask reads eni.private_dns_name, which the EC2 ENI model
        # only populates when the VPC has DNS hostnames enabled.
        ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={"Value": True})
        subnet_id = ec2.create_subnet(
            VpcId=vpc_id, CidrBlock="10.0.1.0/24"
        )["Subnet"]["SubnetId"]
        sg_id = ec2.create_security_group(
            GroupName="baseline-mc-sg", Description="test", VpcId=vpc_id
        )["GroupId"]

        ecs = boto3.client("ecs", region_name="us-east-1")
        cluster = ecs.create_cluster(clusterName="baseline-mc")["cluster"]["clusterArn"]
        task_def = ecs.register_task_definition(
            family="baseline-mc",
            requiresCompatibilities=["FARGATE"],
            networkMode="awsvpc",
            cpu="4096",
            memory="8192",
            containerDefinitions=[{"name": "App", "image": "x", "essential": True, "memory": 8192}],
        )["taskDefinition"]["taskDefinitionArn"]
        monkeypatch.setenv("DATA_BUCKET", "test-data")
        monkeypatch.setenv("CLUSTER_ARN", cluster)
        monkeypatch.setenv("TASK_DEFINITION_ARN", task_def)
        monkeypatch.setenv("CONTAINER_NAME", "App")
        monkeypatch.setenv("SUBNET_IDS", subnet_id)
        monkeypatch.setenv("SECURITY_GROUP_IDS", sg_id)
        yield


def test_launcher_starts_task_and_returns_handle(ecs_env):
    out = handler.handler(
        {"panel_uri": "s3://test-data/lb.parquet", "as_of": "2022-06-23",
         "horizon": 21, "n_paths": 200},
        None,
    )
    assert out["status"] == "ok"
    assert out["result"]["task_arn"]
    assert out["result"]["paths_uri"].startswith("s3://test-data/sessions/")
    assert out["result"]["paths_uri"].endswith("/baseline.pkl")


def test_launcher_rejects_invalid_n_paths(ecs_env):
    out = handler.handler(
        {"panel_uri": "s3://test-data/lb.parquet", "as_of": "2022-06-23",
         "horizon": 21, "n_paths": 0},
        None,
    )
    assert out["status"] == "error"
    assert "n_paths" in out["message"]
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tools/tests/test_run_baseline_mc.py -v
```

Expected: FAIL — handler missing.

- [ ] **Step 3: Implement `tools/lambda/run_baseline_mc/handler.py`**

```python
"""run_baseline_mc tool: launch the baseline-MC Fargate task (async).

Inputs:  {"panel_uri": str, "as_of": "YYYY-MM-DD", "horizon": int,
          "n_paths": int, "n_components": int?, "seed": int?}
Outputs: {"task_arn": str, "paths_uri": str}

Returns immediately; the result PathSet lands at `paths_uri` when the task
finishes. Poll with `check_baseline_mc`.
"""
from __future__ import annotations
import os
import uuid

import boto3

from tools.lambda_.shared import responses
from tools.lambda_.shared.bedrock import bedrock_action


@bedrock_action
def handler(event: dict, _ctx) -> dict:
    horizon = int(event.get("horizon", 0))
    n_paths = int(event.get("n_paths", 0))
    if horizon <= 0 or horizon > 1000:
        return responses.error("horizon must be in (0, 1000]")
    if n_paths <= 0 or n_paths > 50_000:
        return responses.error("n_paths must be in (0, 50000]")
    try:
        panel_uri = event["panel_uri"]
        as_of = event["as_of"]
    except KeyError as e:
        return responses.error(f"missing input: {e}")

    bucket = os.environ["DATA_BUCKET"]
    sid = uuid.uuid4().hex[:12]
    output_key = f"sessions/{sid}/baseline.pkl"

    overrides = {
        "containerOverrides": [{
            "name": os.environ["CONTAINER_NAME"],
            "environment": [
                {"name": "DATA_BUCKET", "value": bucket},
                {"name": "PANEL_URI", "value": panel_uri},
                {"name": "AS_OF", "value": as_of},
                {"name": "HORIZON", "value": str(horizon)},
                {"name": "N_PATHS", "value": str(n_paths)},
                {"name": "N_COMPONENTS", "value": str(int(event.get("n_components", 3)))},
                {"name": "OUTPUT_KEY", "value": output_key},
                {"name": "SEED", "value": str(int(event.get("seed", 0)))},
            ],
        }],
    }
    network = {
        "awsvpcConfiguration": {
            "subnets": os.environ["SUBNET_IDS"].split(","),
            "securityGroups": [g for g in os.environ.get("SECURITY_GROUP_IDS", "").split(",") if g],
            "assignPublicIp": "DISABLED",
        }
    }
    resp = boto3.client("ecs").run_task(
        cluster=os.environ["CLUSTER_ARN"],
        taskDefinition=os.environ["TASK_DEFINITION_ARN"],
        launchType="FARGATE",
        overrides=overrides,
        networkConfiguration=network,
        count=1,
    )
    task_arn = resp["tasks"][0]["taskArn"]
    return responses.ok({
        "task_arn": task_arn,
        "paths_uri": f"s3://{bucket}/{output_key}",
    })
```

- [ ] **Step 4: Run tests, confirm pass**

```bash
pytest tools/tests/test_run_baseline_mc.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/lambda/run_baseline_mc/ tools/tests/test_run_baseline_mc.py
git commit -m "feat(tools): run_baseline_mc launcher Lambda (async ECS RunTask)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 11b: `check_baseline_mc` poll Lambda — task status

**Files:**
- Create: `tools/lambda/check_baseline_mc/__init__.py` (empty)
- Create: `tools/lambda/check_baseline_mc/handler.py`
- Create: `tools/tests/test_check_baseline_mc.py`

Polls the launched Fargate task via `ECS DescribeTasks` and reports whether the
result PathSet is ready. The agent calls this on a loop (Stage 5 system prompt)
until `ready` is true, then proceeds to `price_book`/`blend_paths` on
`paths_uri`.

- [ ] **Step 1: Write the failing test**

`tools/tests/test_check_baseline_mc.py`:
```python
from unittest.mock import patch

from tools.lambda_.check_baseline_mc import handler


def _describe(last_status, exit_code=0):
    container = {"name": "App", "lastStatus": last_status}
    if exit_code is not None:
        container["exitCode"] = exit_code
    return {"tasks": [{"lastStatus": last_status, "containers": [container]}], "failures": []}


def test_check_reports_running(monkeypatch):
    monkeypatch.setenv("CLUSTER_ARN", "baseline-mc")
    with patch.object(handler, "_describe_task", return_value=_describe("RUNNING", exit_code=None)):
        out = handler.handler({"task_arn": "arn:task/abc", "paths_uri": "s3://b/k.pkl"}, None)
    assert out["status"] == "ok"
    assert out["result"]["task_status"] == "RUNNING"
    assert out["result"]["ready"] is False


def test_check_reports_ready_when_stopped_ok(monkeypatch):
    monkeypatch.setenv("CLUSTER_ARN", "baseline-mc")
    with patch.object(handler, "_describe_task", return_value=_describe("STOPPED", exit_code=0)):
        out = handler.handler({"task_arn": "arn:task/abc", "paths_uri": "s3://b/k.pkl"}, None)
    assert out["result"]["ready"] is True
    assert out["result"]["paths_uri"] == "s3://b/k.pkl"


def test_check_reports_failure_when_stopped_nonzero(monkeypatch):
    monkeypatch.setenv("CLUSTER_ARN", "baseline-mc")
    with patch.object(handler, "_describe_task", return_value=_describe("STOPPED", exit_code=1)):
        out = handler.handler({"task_arn": "arn:task/abc", "paths_uri": "s3://b/k.pkl"}, None)
    assert out["status"] == "error"


def test_check_rejects_missing_task_arn(monkeypatch):
    monkeypatch.setenv("CLUSTER_ARN", "baseline-mc")
    out = handler.handler({"paths_uri": "s3://b/k.pkl"}, None)
    assert out["status"] == "error"
    assert "task_arn" in out["message"]
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tools/tests/test_check_baseline_mc.py -v
```

Expected: FAIL — handler missing.

- [ ] **Step 3: Implement `tools/lambda/check_baseline_mc/handler.py`**

```python
"""check_baseline_mc tool: poll the launched baseline-MC Fargate task.

Inputs:  {"task_arn": str, "paths_uri": str}
Outputs: {"task_status": str, "ready": bool, "paths_uri": str}
"""
from __future__ import annotations
import os

import boto3

from tools.lambda_.shared import responses
from tools.lambda_.shared.bedrock import bedrock_action


def _describe_task(task_arn: str) -> dict:
    return boto3.client("ecs").describe_tasks(
        cluster=os.environ["CLUSTER_ARN"], tasks=[task_arn]
    )


@bedrock_action
def handler(event: dict, _ctx) -> dict:
    task_arn = event.get("task_arn")
    paths_uri = event.get("paths_uri")
    if not task_arn:
        return responses.error("missing task_arn")

    desc = _describe_task(task_arn)
    if not desc.get("tasks"):
        return responses.error(f"task {task_arn} not found")
    task = desc["tasks"][0]
    status = task["lastStatus"]

    if status != "STOPPED":
        return responses.ok({"task_status": status, "ready": False, "paths_uri": paths_uri})

    exit_codes = [c.get("exitCode") for c in task.get("containers", [])]
    if any(code not in (0, None) for code in exit_codes):
        return responses.error(f"baseline MC task failed (exit codes {exit_codes})")
    return responses.ok({"task_status": status, "ready": True, "paths_uri": paths_uri})
```

- [ ] **Step 4: Run tests, confirm pass**

```bash
pytest tools/tests/test_check_baseline_mc.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/lambda/check_baseline_mc/ tools/tests/test_check_baseline_mc.py
git commit -m "feat(tools): check_baseline_mc poll Lambda (ECS DescribeTasks)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 11c: `run_chronos2` launcher Lambda — start the Fargate task

**Files:**
- Create: `tools/lambda/run_chronos2/__init__.py` (empty)
- Create: `tools/lambda/run_chronos2/handler.py`
- Create: `tools/tests/test_run_chronos2.py`

Mirrors the `run_baseline_mc` launcher (Task 11a): a thin `boto3`-only Lambda
that starts the chronos2 Fargate task (Task 11) via `ecs.run_task` and returns
immediately with a `{task_arn, paths_uri}` handle. The agent polls with
`check_chronos2` (Task 11d). Passes the covariates URI, optional conditioning,
and the `CHRONOS2_ENDPOINT` name through as container env overrides.

- [ ] **Step 1: Write the failing test**

`tools/tests/test_run_chronos2.py`:
```python
import boto3
import json
import pytest
from moto import mock_aws

from tools.lambda_.run_chronos2 import handler


@pytest.fixture
def ecs_env(aws_creds, monkeypatch):
    with mock_aws():
        ec2 = boto3.client("ec2", region_name="us-east-1")
        vpc_id = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
        ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={"Value": True})
        subnet_id = ec2.create_subnet(
            VpcId=vpc_id, CidrBlock="10.0.1.0/24"
        )["Subnet"]["SubnetId"]
        sg_id = ec2.create_security_group(
            GroupName="chronos2-sg", Description="test", VpcId=vpc_id
        )["GroupId"]

        ecs = boto3.client("ecs", region_name="us-east-1")
        cluster = ecs.create_cluster(clusterName="chronos2")["cluster"]["clusterArn"]
        task_def = ecs.register_task_definition(
            family="chronos2",
            requiresCompatibilities=["FARGATE"],
            networkMode="awsvpc",
            cpu="4096",
            memory="8192",
            containerDefinitions=[{"name": "App", "image": "x", "essential": True, "memory": 8192}],
        )["taskDefinition"]["taskDefinitionArn"]
        monkeypatch.setenv("DATA_BUCKET", "test-data")
        monkeypatch.setenv("CLUSTER_ARN", cluster)
        monkeypatch.setenv("TASK_DEFINITION_ARN", task_def)
        monkeypatch.setenv("CONTAINER_NAME", "App")
        monkeypatch.setenv("SUBNET_IDS", subnet_id)
        monkeypatch.setenv("SECURITY_GROUP_IDS", sg_id)
        monkeypatch.setenv("CHRONOS2_ENDPOINT", "chronos2-demo-ep")
        yield


def test_launcher_starts_task_and_returns_handle(ecs_env):
    out = handler.handler(
        {"panel_uri": "s3://test-data/lb.parquet", "as_of": "2022-06-23",
         "horizon": 21, "n_paths": 200, "covariates_uri": "s3://test-data/cov.parquet"},
        None,
    )
    assert out["status"] == "ok"
    assert out["result"]["task_arn"]
    assert out["result"]["paths_uri"].startswith("s3://test-data/sessions/")
    assert out["result"]["paths_uri"].endswith("/chronos2.pkl")


def test_launcher_rejects_invalid_n_paths(ecs_env):
    out = handler.handler(
        {"panel_uri": "s3://test-data/lb.parquet", "as_of": "2022-06-23",
         "horizon": 21, "n_paths": 0},
        None,
    )
    assert out["status"] == "error"
    assert "n_paths" in out["message"]
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tools/tests/test_run_chronos2.py -v
```

Expected: FAIL — handler missing.

- [ ] **Step 3: Implement `tools/lambda/run_chronos2/handler.py`**

```python
"""run_chronos2 tool: launch the chronos2 Fargate task (async).

Inputs:  {"panel_uri": str, "as_of": "YYYY-MM-DD", "horizon": int,
          "n_paths": int, "covariates_uri": str?, "conditioning": dict?,
          "seed": int?}
Outputs: {"task_arn": str, "paths_uri": str}

Returns immediately; the result PathSet lands at `paths_uri` when the task
finishes. Poll with `check_chronos2`. The chronos2 endpoint call (AutoGluon
Cloud) runs in the Fargate container, not here.
"""
from __future__ import annotations
import json
import os
import uuid

import boto3

from tools.lambda_.shared import responses
from tools.lambda_.shared.bedrock import bedrock_action


@bedrock_action
def handler(event: dict, _ctx) -> dict:
    horizon = int(event.get("horizon", 0))
    n_paths = int(event.get("n_paths", 0))
    if horizon <= 0 or horizon > 1000:
        return responses.error("horizon must be in (0, 1000]")
    if n_paths <= 0 or n_paths > 20_000:
        return responses.error("n_paths must be in (0, 20000]")
    try:
        panel_uri = event["panel_uri"]
        as_of = event["as_of"]
    except KeyError as e:
        return responses.error(f"missing input: {e}")

    bucket = os.environ["DATA_BUCKET"]
    sid = uuid.uuid4().hex[:12]
    output_key = f"sessions/{sid}/chronos2.pkl"

    env = [
        {"name": "DATA_BUCKET", "value": bucket},
        {"name": "PANEL_URI", "value": panel_uri},
        {"name": "AS_OF", "value": as_of},
        {"name": "HORIZON", "value": str(horizon)},
        {"name": "N_PATHS", "value": str(n_paths)},
        {"name": "OUTPUT_KEY", "value": output_key},
        {"name": "CHRONOS2_ENDPOINT", "value": os.environ["CHRONOS2_ENDPOINT"]},
        {"name": "SEED", "value": str(int(event.get("seed", 0)))},
    ]
    if event.get("covariates_uri"):
        env.append({"name": "COVARIATES_URI", "value": event["covariates_uri"]})
    if event.get("conditioning"):
        env.append({"name": "CONDITIONING_JSON", "value": json.dumps(event["conditioning"])})

    overrides = {"containerOverrides": [{"name": os.environ["CONTAINER_NAME"], "environment": env}]}
    network = {
        "awsvpcConfiguration": {
            "subnets": os.environ["SUBNET_IDS"].split(","),
            "securityGroups": [g for g in os.environ.get("SECURITY_GROUP_IDS", "").split(",") if g],
            "assignPublicIp": "DISABLED",
        }
    }
    resp = boto3.client("ecs").run_task(
        cluster=os.environ["CLUSTER_ARN"],
        taskDefinition=os.environ["TASK_DEFINITION_ARN"],
        launchType="FARGATE",
        overrides=overrides,
        networkConfiguration=network,
        count=1,
    )
    task_arn = resp["tasks"][0]["taskArn"]
    return responses.ok({
        "task_arn": task_arn,
        "paths_uri": f"s3://{bucket}/{output_key}",
    })
```

> **Note:** the entrypoint (Task 11) reads `CONDITIONING_JSON` only if you wire
> it; the Task 11 entrypoint shown omits conditioning for brevity. If the demo
> exercises the what-if (conditioning) beat through the agent, add a
> `conditioning=json.loads(os.environ["CONDITIONING_JSON"])` branch to the
> entrypoint and pass it to `simulate_chronos2` — flag this when you reach it.

- [ ] **Step 4: Run tests, confirm pass**

```bash
pytest tools/tests/test_run_chronos2.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/lambda/run_chronos2/ tools/tests/test_run_chronos2.py
git commit -m "feat(tools): run_chronos2 launcher Lambda (async ECS RunTask)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 11d: `check_chronos2` poll Lambda — task status

**Files:**
- Create: `tools/lambda/check_chronos2/__init__.py` (empty)
- Create: `tools/lambda/check_chronos2/handler.py`
- Create: `tools/tests/test_check_chronos2.py`

Identical in shape to `check_baseline_mc` (Task 11b): polls the chronos2
Fargate task via `ECS DescribeTasks` and reports `ready`. The agent loops on it
until `ready`, then blends `paths_uri` with the baseline PathSet.

- [ ] **Step 1: Write the failing test**

`tools/tests/test_check_chronos2.py`:
```python
from unittest.mock import patch

from tools.lambda_.check_chronos2 import handler


def _describe(last_status, exit_code=0):
    container = {"name": "App", "lastStatus": last_status}
    if exit_code is not None:
        container["exitCode"] = exit_code
    return {"tasks": [{"lastStatus": last_status, "containers": [container]}], "failures": []}


def test_check_reports_running(monkeypatch):
    monkeypatch.setenv("CLUSTER_ARN", "chronos2")
    with patch.object(handler, "_describe_task", return_value=_describe("RUNNING", exit_code=None)):
        out = handler.handler({"task_arn": "arn:task/abc", "paths_uri": "s3://b/k.pkl"}, None)
    assert out["status"] == "ok"
    assert out["result"]["task_status"] == "RUNNING"
    assert out["result"]["ready"] is False


def test_check_reports_ready_when_stopped_ok(monkeypatch):
    monkeypatch.setenv("CLUSTER_ARN", "chronos2")
    with patch.object(handler, "_describe_task", return_value=_describe("STOPPED", exit_code=0)):
        out = handler.handler({"task_arn": "arn:task/abc", "paths_uri": "s3://b/k.pkl"}, None)
    assert out["result"]["ready"] is True
    assert out["result"]["paths_uri"] == "s3://b/k.pkl"


def test_check_reports_failure_when_stopped_nonzero(monkeypatch):
    monkeypatch.setenv("CLUSTER_ARN", "chronos2")
    with patch.object(handler, "_describe_task", return_value=_describe("STOPPED", exit_code=1)):
        out = handler.handler({"task_arn": "arn:task/abc", "paths_uri": "s3://b/k.pkl"}, None)
    assert out["status"] == "error"


def test_check_rejects_missing_task_arn(monkeypatch):
    monkeypatch.setenv("CLUSTER_ARN", "chronos2")
    out = handler.handler({"paths_uri": "s3://b/k.pkl"}, None)
    assert out["status"] == "error"
    assert "task_arn" in out["message"]
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tools/tests/test_check_chronos2.py -v
```

Expected: FAIL — handler missing.

- [ ] **Step 3: Implement `tools/lambda/check_chronos2/handler.py`**

```python
"""check_chronos2 tool: poll the launched chronos2 Fargate task.

Inputs:  {"task_arn": str, "paths_uri": str}
Outputs: {"task_status": str, "ready": bool, "paths_uri": str}
"""
from __future__ import annotations
import os

import boto3

from tools.lambda_.shared import responses
from tools.lambda_.shared.bedrock import bedrock_action


def _describe_task(task_arn: str) -> dict:
    return boto3.client("ecs").describe_tasks(
        cluster=os.environ["CLUSTER_ARN"], tasks=[task_arn]
    )


@bedrock_action
def handler(event: dict, _ctx) -> dict:
    task_arn = event.get("task_arn")
    paths_uri = event.get("paths_uri")
    if not task_arn:
        return responses.error("missing task_arn")

    desc = _describe_task(task_arn)
    if not desc.get("tasks"):
        return responses.error(f"task {task_arn} not found")
    task = desc["tasks"][0]
    status = task["lastStatus"]

    if status != "STOPPED":
        return responses.ok({"task_status": status, "ready": False, "paths_uri": paths_uri})

    exit_codes = [c.get("exitCode") for c in task.get("containers", [])]
    if any(code not in (0, None) for code in exit_codes):
        return responses.error(f"chronos2 task failed (exit codes {exit_codes})")
    return responses.ok({"task_status": status, "ready": True, "paths_uri": paths_uri})
```

- [ ] **Step 4: Run tests, confirm pass**

```bash
pytest tools/tests/test_check_chronos2.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/lambda/check_chronos2/ tools/tests/test_check_chronos2.py
git commit -m "feat(tools): check_chronos2 poll Lambda (ECS DescribeTasks)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Stage 4 — Tools stack wiring & IAM

### Task 12: Lambda authorizer (Node 20) — API key check

**Files:**
- Create: `tools/lambda/authorizer/handler.ts`
- Create: `tools/lambda/authorizer/package.json`
- Create: `tools/lambda/authorizer/tsconfig.json`
- Create: `tools/lambda/authorizer/test/handler.test.ts`
- Create: `tools/lambda/authorizer/jest.config.js`

Demo-grade auth: an API Gateway request authorizer that compares a
header key to a SecretsManager-stored value. Cognito-swappable (spec
§9). Single allow/deny policy.

- [ ] **Step 1: Write the failing test**

`tools/lambda/authorizer/test/handler.test.ts`:
```typescript
import { handler } from '../handler';

const baseEvent = {
  type: 'REQUEST',
  methodArn: 'arn:aws:execute-api:us-east-1:123:api/prod/POST/agent',
  headers: {} as Record<string, string>,
};

describe('authorizer', () => {
  beforeEach(() => {
    process.env.API_KEY = 'expected-key';
  });

  test('Allow when header matches', async () => {
    const ev = { ...baseEvent, headers: { 'x-api-key': 'expected-key' } };
    const out = await handler(ev as any);
    expect(out.policyDocument.Statement[0].Effect).toBe('Allow');
  });

  test('Deny when header missing', async () => {
    const out = await handler(baseEvent as any);
    expect(out.policyDocument.Statement[0].Effect).toBe('Deny');
  });

  test('Deny when header wrong', async () => {
    const ev = { ...baseEvent, headers: { 'x-api-key': 'wrong' } };
    const out = await handler(ev as any);
    expect(out.policyDocument.Statement[0].Effect).toBe('Deny');
  });

  test('Header is case-insensitive', async () => {
    const ev = { ...baseEvent, headers: { 'X-Api-Key': 'expected-key' } };
    const out = await handler(ev as any);
    expect(out.policyDocument.Statement[0].Effect).toBe('Allow');
  });
});
```

- [ ] **Step 2: Create `package.json` + `tsconfig.json` + `jest.config.js`**

`tools/lambda/authorizer/package.json`:
```json
{
  "name": "authorizer",
  "version": "0.1.0",
  "private": true,
  "main": "handler.js",
  "scripts": {
    "build": "tsc",
    "test": "jest"
  },
  "devDependencies": {
    "@types/jest": "^29.5.12",
    "@types/node": "^20.11.0",
    "jest": "^29.7.0",
    "ts-jest": "^29.1.2",
    "typescript": "^5.4.0"
  }
}
```

`tools/lambda/authorizer/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "commonjs",
    "lib": ["ES2022"],
    "strict": true,
    "esModuleInterop": true,
    "outDir": ".",
    "rootDir": ".",
    "skipLibCheck": true,
    "declaration": false
  },
  "include": ["handler.ts", "test/**/*.ts"]
}
```

`tools/lambda/authorizer/jest.config.js`:
```javascript
module.exports = {
  testEnvironment: 'node',
  preset: 'ts-jest',
  testMatch: ['**/test/**/*.test.ts'],
};
```

- [ ] **Step 3: Run, confirm fail**

```bash
cd tools/lambda/authorizer && npm install && npm test
```

Expected: FAIL — `handler` module missing.

- [ ] **Step 4: Implement `tools/lambda/authorizer/handler.ts`**

```typescript
type AuthEvent = {
  type: 'REQUEST';
  methodArn: string;
  headers: Record<string, string>;
};

type Policy = {
  principalId: string;
  policyDocument: {
    Version: '2012-10-17';
    Statement: Array<{ Action: string; Effect: 'Allow' | 'Deny'; Resource: string }>;
  };
};

function buildPolicy(effect: 'Allow' | 'Deny', resource: string): Policy {
  return {
    principalId: 'demo-user',
    policyDocument: {
      Version: '2012-10-17',
      Statement: [{ Action: 'execute-api:Invoke', Effect: effect, Resource: resource }],
    },
  };
}

export async function handler(event: AuthEvent): Promise<Policy> {
  const expected = process.env.API_KEY;
  if (!expected) {
    return buildPolicy('Deny', event.methodArn);
  }
  // Case-insensitive header lookup.
  const headers = event.headers ?? {};
  const provided = Object.keys(headers).find(
    (k) => k.toLowerCase() === 'x-api-key'
  );
  if (!provided) {
    return buildPolicy('Deny', event.methodArn);
  }
  return headers[provided] === expected
    ? buildPolicy('Allow', event.methodArn)
    : buildPolicy('Deny', event.methodArn);
}
```

- [ ] **Step 5: Run tests, confirm pass**

```bash
cd tools/lambda/authorizer && npm test
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add tools/lambda/authorizer/
git commit -m "feat(tools): API Gateway authorizer Lambda (API key check)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 13: Tools stack — wire Lambdas + Fargate task + ECR + IAM

**Files:**
- Create: `infra/lib/tools-stack.ts`
- Create: `infra/test/tools-stack.test.ts`
- Modify: `infra/bin/app.ts`

The big plumbing task. CDK constructs:
- A Python Lambda layer built from `src/chronos2_demo/` — also bundles the demo book (`data/sample_book.json`) so `price_book`/`blend_paths` read it via `BOOK_PATH=/opt/python/data/sample_book.json`.
- Nine Python Lambdas (`load_data`, `blend_paths`, `price_book`, `plot`, `lookup_use_case`, `run_chronos2` launcher, `check_chronos2` poll, `run_baseline_mc` launcher, `check_baseline_mc` poll) sharing the layer. **`run_chronos2` is a launcher, not a proxy** — the AutoGluon Cloud endpoint call is too heavy for Lambda, so it runs in a Fargate task (Task 11) like baseline-MC.
- One Node 20 authorizer Lambda.
- **Two** ECR repos + **two** Fargate task definitions (`baseline_mc`, `chronos2`) sharing **one** ECS cluster. Each launcher Lambda starts its task via `ecs:RunTask` (+ `iam:PassRole`); each poll Lambda reads `ecs:DescribeTasks`.
- The **chronos2 task role** holds `sagemaker:InvokeEndpoint` (AutoGluon's `TimeSeriesEndpoint.predict` invokes the SageMaker runtime under the hood); the task gets `CHRONOS2_ENDPOINT` as a container env var.
- IAM: each Lambda/task gets only the S3 bucket, SageMaker endpoint, and ECS perms it needs.
- Public surface for consumer stacks: `fn*` function refs (incl. `fnRunChronos2`, `fnCheckChronos2`), `coreLayer`, `apiKeySecretArn`, `baselineMcCluster`, `baselineMcTaskDef`, `chronos2TaskDef`.
- `chronos2EndpointName` is **optional** (defaults to `chronos2-demo-ep`) so consumer-stack tests can omit it.
- All resources tagged `chronos2-demo:teardown=on`.

- [ ] **Step 1: Write the failing snapshot test**

`infra/test/tools-stack.test.ts`:
```typescript
import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { NetworkStack } from '../lib/network-stack';
import { StorageStack } from '../lib/storage-stack';
import { ToolsStack } from '../lib/tools-stack';

function build() {
  const app = new cdk.App();
  const network = new NetworkStack(app, 'Net');
  const storage = new StorageStack(app, 'Storage');
  const tools = new ToolsStack(app, 'Tools', {
    vpc: network.vpc,
    dataBucket: storage.dataBucket,
    plotsBucket: storage.plotsBucket,
    chronos2EndpointName: 'chronos2-demo-ep',
  });
  return Template.fromStack(tools);
}

test('creates 9 Python Lambdas + 1 Node authorizer', () => {
  const t = build();
  // 9 Python tool Lambdas (load_data, blend_paths, price_book, plot,
  // lookup_use_case, run_chronos2 launcher, check_chronos2, run_baseline_mc
  // launcher, check_baseline_mc) + 1 Node authorizer = 10. Allow >= 10 to
  // absorb CDK custom-resource Lambdas.
  const fns = t.findResources('AWS::Lambda::Function');
  expect(Object.keys(fns).length).toBeGreaterThanOrEqual(10);
});

test('creates one ECS cluster + two Fargate task definitions', () => {
  const t = build();
  t.resourceCountIs('AWS::ECS::Cluster', 1);
  // baseline_mc + chronos2
  t.resourceCountIs('AWS::ECS::TaskDefinition', 2);
});

test('creates two ECR repositories with image scan on push', () => {
  const t = build();
  t.resourceCountIs('AWS::ECR::Repository', 2);
  t.hasResourceProperties('AWS::ECR::Repository', Match.objectLike({
    ImageScanningConfiguration: { ScanOnPush: true },
  }));
});

test('creates the Lambda layer for chronos2_demo', () => {
  const t = build();
  t.resourceCountIs('AWS::Lambda::LayerVersion', 1);
});

test('exposes lambda function references', () => {
  const app = new cdk.App();
  const network = new NetworkStack(app, 'Net');
  const storage = new StorageStack(app, 'Storage');
  const tools = new ToolsStack(app, 'Tools', {
    vpc: network.vpc,
    dataBucket: storage.dataBucket,
    plotsBucket: storage.plotsBucket,
    chronos2EndpointName: 'chronos2-demo-ep',
  });
  expect(tools.fnLoadData).toBeDefined();
  expect(tools.fnBlendPaths).toBeDefined();
  expect(tools.fnPriceBook).toBeDefined();
  expect(tools.fnPlot).toBeDefined();
  expect(tools.fnLookupUseCase).toBeDefined();
  expect(tools.fnRunChronos2).toBeDefined();
  expect(tools.fnCheckChronos2).toBeDefined();
  expect(tools.fnRunBaselineMc).toBeDefined();
  expect(tools.fnCheckBaselineMc).toBeDefined();
  expect(tools.fnAuthorizer).toBeDefined();
  expect(tools.coreLayer).toBeDefined();
  expect(tools.apiKeySecretArn).toBeDefined();
  expect(tools.baselineMcTaskDef).toBeDefined();
  expect(tools.baselineMcCluster).toBeDefined();
  expect(tools.chronos2TaskDef).toBeDefined();
});
```

- [ ] **Step 2: Run, confirm fail**

```bash
cd infra && npm test -- tools-stack
```

Expected: FAIL — module missing.

- [ ] **Step 3: Implement `infra/lib/tools-stack.ts`**

```typescript
import * as cdk from 'aws-cdk-lib';
import * as path from 'path';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as secrets from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';

export interface ToolsStackProps extends cdk.StackProps {
  vpc: ec2.IVpc;
  dataBucket: s3.IBucket;
  plotsBucket: s3.IBucket;
  // Optional: the Plan A SageMaker endpoint name. Defaults so consumer-stack
  // tests can construct ToolsStack without threading it through.
  chronos2EndpointName?: string;
}

export class ToolsStack extends cdk.Stack {
  public readonly fnLoadData: lambda.IFunction;
  public readonly fnBlendPaths: lambda.IFunction;
  public readonly fnPriceBook: lambda.IFunction;
  public readonly fnPlot: lambda.IFunction;
  public readonly fnLookupUseCase: lambda.IFunction;
  public readonly fnRunChronos2: lambda.IFunction;
  public readonly fnCheckChronos2: lambda.IFunction;
  public readonly fnRunBaselineMc: lambda.IFunction;
  public readonly fnCheckBaselineMc: lambda.IFunction;
  public readonly fnAuthorizer: lambda.IFunction;
  public readonly baselineMcTaskDef: ecs.FargateTaskDefinition;
  public readonly baselineMcCluster: ecs.ICluster;
  public readonly chronos2TaskDef: ecs.FargateTaskDefinition;
  public readonly apiKeySecret: secrets.ISecret;
  // Consumer stacks (Api, Agent) need the layer + secret ARN directly.
  public readonly coreLayer: lambda.ILayerVersion;
  public readonly apiKeySecretArn: string;

  constructor(scope: Construct, id: string, props: ToolsStackProps) {
    super(scope, id, props);

    const repoRoot = path.resolve(__dirname, '..', '..');
    const chronos2EndpointName = props.chronos2EndpointName ?? 'chronos2-demo-ep';

    // Lambda layer with chronos2_demo source + shared helpers + the demo book.
    // The book is bundled into the layer (it resolves under /opt at runtime, so
    // handlers read BOOK_PATH rather than book.DEFAULT_BOOK_PATH).
    const coreLayer = new lambda.LayerVersion(this, 'CoreLayer', {
      code: lambda.Code.fromAsset(repoRoot, {
        bundling: {
          image: lambda.Runtime.PYTHON_3_11.bundlingImage,
          // Force the x86_64 Lambda target regardless of the build host's arch
          // (e.g. Apple Silicon), so the wheels match the Lambda architecture.
          platform: 'linux/amd64',
          command: [
            'bash', '-c', [
              'mkdir -p /asset-output/python',
              'cp -r src/chronos2_demo /asset-output/python/',
              'mkdir -p /asset-output/python/tools/lambda_',
              'cp tools/__init__.py /asset-output/python/tools/__init__.py || touch /asset-output/python/tools/__init__.py',
              'touch /asset-output/python/tools/lambda_/__init__.py',
              'cp -r tools/lambda/shared /asset-output/python/tools/lambda_/shared',
              'mkdir -p /asset-output/python/data',
              'cp data/sample_book.json /asset-output/python/data/sample_book.json',
              // --only-binary=:all: forces manylinux wheels; without it pip pulls
              // the latest numpy sdist, which has no cp311 wheel and fails to
              // compile under the build image's GCC.
              'pip install --only-binary=:all: --target /asset-output/python numpy scipy pandas scikit-learn matplotlib pyarrow boto3',
            ].join(' && '),
          ],
        },
      }),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_11],
      description: 'chronos2_demo + tools.lambda_.shared + demo book + scientific deps',
    });
    this.coreLayer = coreLayer;

    // The book lands at /opt/python/data/sample_book.json inside any function
    // that attaches the layer.
    const BOOK_PATH = '/opt/python/data/sample_book.json';

    const commonEnv = {
      DATA_BUCKET: props.dataBucket.bucketName,
      PLOTS_BUCKET: props.plotsBucket.bucketName,
    };

    const py = (id: string, dir: string, env: Record<string, string> = {}) =>
      new lambda.Function(this, id, {
        runtime: lambda.Runtime.PYTHON_3_11,
        architecture: lambda.Architecture.X86_64,
        handler: 'handler.handler',
        code: lambda.Code.fromAsset(path.join(repoRoot, 'tools', 'lambda', dir)),
        layers: [coreLayer],
        memorySize: 1024,
        timeout: cdk.Duration.seconds(30),
        environment: { ...commonEnv, ...env },
        logRetention: logs.RetentionDays.ONE_WEEK,
      });

    this.fnLoadData = py('LoadData', 'load_data');
    this.fnBlendPaths = py('BlendPaths', 'blend_paths', { BOOK_PATH });
    this.fnPriceBook = py('PriceBook', 'price_book', { BOOK_PATH });
    this.fnPlot = py('Plot', 'plot');
    this.fnLookupUseCase = py('LookupUseCase', 'lookup_use_case', {
      KNOWLEDGE_DIR: '/var/task/knowledge',
    });

    // S3 perms — least-privilege per Lambda. (run_chronos2 is a Fargate
    // launcher, wired below alongside the chronos2 task definition.)
    props.dataBucket.grantReadWrite(this.fnLoadData);
    props.dataBucket.grantReadWrite(this.fnBlendPaths);
    props.dataBucket.grantReadWrite(this.fnPriceBook);
    props.dataBucket.grantRead(this.fnPlot);
    props.plotsBucket.grantReadWrite(this.fnPlot);

    // Authorizer (Node 20).
    this.apiKeySecret = new secrets.Secret(this, 'ApiKey', {
      description: 'Demo-grade API key for AgentCore endpoints',
      generateSecretString: { excludePunctuation: true, passwordLength: 32 },
    });
    this.apiKeySecretArn = this.apiKeySecret.secretArn;
    this.fnAuthorizer = new lambda.Function(this, 'Authorizer', {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: 'handler.handler',
      code: lambda.Code.fromAsset(path.join(repoRoot, 'tools', 'lambda', 'authorizer')),
      timeout: cdk.Duration.seconds(5),
      memorySize: 256,
      environment: {
        // Resolve at runtime via SecretsManager extension or directly read.
        API_KEY_SECRET_ARN: this.apiKeySecret.secretArn,
      },
      logRetention: logs.RetentionDays.ONE_WEEK,
    });
    this.apiKeySecret.grantRead(this.fnAuthorizer);

    // Fargate baseline_mc.
    const repo = new ecr.Repository(this, 'BaselineMcRepo', {
      imageScanOnPush: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      emptyOnDelete: true,
    });
    const cluster = new ecs.Cluster(this, 'BaselineMcCluster', {
      vpc: props.vpc,
    });
    this.baselineMcCluster = cluster;
    const baselineMcSg = new ec2.SecurityGroup(this, 'BaselineMcSg', {
      vpc: props.vpc,
      description: 'Egress-only SG for the baseline-MC Fargate task',
    });
    this.baselineMcTaskDef = new ecs.FargateTaskDefinition(this, 'BaselineMcTaskDef', {
      cpu: 4096,
      memoryLimitMiB: 8192,
    });
    this.baselineMcTaskDef.addContainer('App', {
      image: ecs.ContainerImage.fromEcrRepository(repo, 'latest'),
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'baseline-mc',
        logRetention: logs.RetentionDays.ONE_WEEK,
      }),
      environment: { DATA_BUCKET: props.dataBucket.bucketName },
    });
    props.dataBucket.grantReadWrite(this.baselineMcTaskDef.taskRole);

    // run_baseline_mc launcher Lambda (starts the Fargate task; returns a handle).
    const privateSubnetIds = props.vpc.selectSubnets({
      subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
    }).subnetIds;
    this.fnRunBaselineMc = py('RunBaselineMc', 'run_baseline_mc', {
      CLUSTER_ARN: cluster.clusterArn,
      TASK_DEFINITION_ARN: this.baselineMcTaskDef.taskDefinitionArn,
      CONTAINER_NAME: 'App',
      SUBNET_IDS: cdk.Fn.join(',', privateSubnetIds),
      SECURITY_GROUP_IDS: baselineMcSg.securityGroupId,
    });
    props.dataBucket.grantRead(this.fnRunBaselineMc);
    this.fnRunBaselineMc.addToRolePolicy(new iam.PolicyStatement({
      actions: ['ecs:RunTask'],
      resources: [this.baselineMcTaskDef.taskDefinitionArn],
    }));
    this.fnRunBaselineMc.addToRolePolicy(new iam.PolicyStatement({
      actions: ['iam:PassRole'],
      resources: [
        this.baselineMcTaskDef.taskRole.roleArn,
        this.baselineMcTaskDef.executionRole!.roleArn,
      ],
    }));

    // check_baseline_mc poll Lambda (DescribeTasks on the cluster).
    this.fnCheckBaselineMc = py('CheckBaselineMc', 'check_baseline_mc', {
      CLUSTER_ARN: cluster.clusterArn,
    });
    this.fnCheckBaselineMc.addToRolePolicy(new iam.PolicyStatement({
      actions: ['ecs:DescribeTasks'],
      resources: ['*'],
    }));

    // Fargate chronos2 — same shared cluster, its own ECR repo + task def.
    // The AutoGluon Cloud endpoint call (autogluon-cloud, heavy) runs here, not
    // in a Lambda. The task role invokes the SageMaker endpoint under the hood.
    const chronos2Repo = new ecr.Repository(this, 'Chronos2Repo', {
      imageScanOnPush: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      emptyOnDelete: true,
    });
    const chronos2Sg = new ec2.SecurityGroup(this, 'Chronos2Sg', {
      vpc: props.vpc,
      description: 'Egress-only SG for the chronos2 Fargate task',
    });
    this.chronos2TaskDef = new ecs.FargateTaskDefinition(this, 'Chronos2TaskDef', {
      cpu: 4096,
      memoryLimitMiB: 8192,
    });
    this.chronos2TaskDef.addContainer('App', {
      image: ecs.ContainerImage.fromEcrRepository(chronos2Repo, 'latest'),
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'chronos2',
        logRetention: logs.RetentionDays.ONE_WEEK,
      }),
      environment: {
        DATA_BUCKET: props.dataBucket.bucketName,
        CHRONOS2_ENDPOINT: chronos2EndpointName,
      },
    });
    props.dataBucket.grantReadWrite(this.chronos2TaskDef.taskRole);
    // AutoGluon's TimeSeriesEndpoint.predict invokes the SageMaker runtime.
    this.chronos2TaskDef.taskRole.addToPrincipalPolicy(new iam.PolicyStatement({
      actions: ['sagemaker:InvokeEndpoint'],
      resources: [
        `arn:${this.partition}:sagemaker:${this.region}:${this.account}:endpoint/${chronos2EndpointName}`,
      ],
    }));

    // run_chronos2 launcher Lambda (starts the chronos2 Fargate task).
    this.fnRunChronos2 = py('RunChronos2', 'run_chronos2', {
      CLUSTER_ARN: cluster.clusterArn,
      TASK_DEFINITION_ARN: this.chronos2TaskDef.taskDefinitionArn,
      CONTAINER_NAME: 'App',
      SUBNET_IDS: cdk.Fn.join(',', privateSubnetIds),
      SECURITY_GROUP_IDS: chronos2Sg.securityGroupId,
      CHRONOS2_ENDPOINT: chronos2EndpointName,
    });
    props.dataBucket.grantRead(this.fnRunChronos2);
    this.fnRunChronos2.addToRolePolicy(new iam.PolicyStatement({
      actions: ['ecs:RunTask'],
      resources: [this.chronos2TaskDef.taskDefinitionArn],
    }));
    this.fnRunChronos2.addToRolePolicy(new iam.PolicyStatement({
      actions: ['iam:PassRole'],
      resources: [
        this.chronos2TaskDef.taskRole.roleArn,
        this.chronos2TaskDef.executionRole!.roleArn,
      ],
    }));

    // check_chronos2 poll Lambda (DescribeTasks on the cluster).
    this.fnCheckChronos2 = py('CheckChronos2', 'check_chronos2', {
      CLUSTER_ARN: cluster.clusterArn,
    });
    this.fnCheckChronos2.addToRolePolicy(new iam.PolicyStatement({
      actions: ['ecs:DescribeTasks'],
      resources: ['*'],
    }));

    new cdk.CfnOutput(this, 'ApiKeySecretArnOut', { value: this.apiKeySecretArn });

    cdk.Tags.of(this).add('chronos2-demo:teardown', 'on');
  }
}
```

- [ ] **Step 4: Wire into `infra/bin/app.ts`**

Replace the file with:

```typescript
#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { NetworkStack } from '../lib/network-stack';
import { StorageStack } from '../lib/storage-stack';
import { ToolsStack } from '../lib/tools-stack';

const app = new cdk.App();
const env = { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION ?? 'us-east-1' };
const demoTag = app.node.tryGetContext('demoTag') ?? 'chronos2-demo';
const chronos2EndpointName = process.env.CHRONOS2_ENDPOINT_NAME ?? 'chronos2-demo-ep';

cdk.Tags.of(app).add('Project', demoTag);
cdk.Tags.of(app).add('chronos2-demo:teardown', 'on');

const network = new NetworkStack(app, 'Chronos2DemoNetwork', { env });
const storage = new StorageStack(app, 'Chronos2DemoStorage', { env });
const tools = new ToolsStack(app, 'Chronos2DemoTools', {
  env,
  vpc: network.vpc,
  dataBucket: storage.dataBucket,
  plotsBucket: storage.plotsBucket,
  chronos2EndpointName,
});

app.synth();
```

- [ ] **Step 5: Run tests, confirm pass**

```bash
cd infra && npm test
```

Expected: previous tests pass + 5 new tools-stack tests pass.

- [ ] **Step 6: Synth check**

```bash
cd infra && npx cdk synth Chronos2DemoTools > /dev/null
```

Expected: no errors. (The Docker bundling for the layer requires Docker
available locally; skip with `--app 'npx ts-node ... --no-bundle'` if CI
isn't able to bundle.)

- [ ] **Step 7: Commit**

```bash
git add infra/lib/tools-stack.ts infra/test/tools-stack.test.ts infra/bin/app.ts
git commit -m "feat(infra): tools stack — Lambdas, layer, Fargate, ECR, authorizer

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

> _Continue with `2026-05-22-plan-b-ux-agent-part-5.md` (Stage 5 — AgentCore agent + action groups, Tasks 14-15)._
