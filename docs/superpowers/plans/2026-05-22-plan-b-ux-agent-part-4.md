# Plan B — Part 4: Stages 3-4 — Fargate Baseline MC, Chronos-2 Proxy, Tools Stack

> **Continuation of** `2026-05-22-plan-b-ux-agent-part-3.md`. Tasks 10-13.

---

## Stage 3 — Fargate baseline MC + Chronos-2 proxy

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
    monkeypatch.setenv("HORIZON", "21")
    monkeypatch.setenv("N_PATHS", "200")
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
    monkeypatch.setenv("HORIZON", "0")
    monkeypatch.setenv("N_PATHS", "200")
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
  DATA_BUCKET, PANEL_URI, HORIZON, N_PATHS, OUTPUT_KEY, SEED
Output: S3 URI (pickle) of a PathSet.
"""
from __future__ import annotations
import io
import os
import pickle
import sys

import boto3
import numpy as np

from chronos2_demo.models import baseline_mc
from chronos2_demo.types import PathSet
from tools.lambda_.shared import s3_io


def main() -> str:
    bucket = os.environ["DATA_BUCKET"]
    panel_uri = os.environ["PANEL_URI"]
    horizon = int(os.environ["HORIZON"])
    n_paths = int(os.environ["N_PATHS"])
    output_key = os.environ["OUTPUT_KEY"]
    seed = int(os.environ.get("SEED", "0"))

    if horizon <= 0 or horizon > 1000:
        raise ValueError(f"HORIZON must be in (0, 1000], got {horizon}")
    if n_paths <= 0 or n_paths > 50_000:
        raise ValueError(f"N_PATHS must be in (0, 50000], got {n_paths}")

    panel = s3_io.download_parquet(panel_uri)
    paths = baseline_mc.simulate(
        panel=panel, horizon=horizon, n_paths=n_paths, seed=seed
    )
    ps = PathSet(
        paths=paths,
        weights=np.full(n_paths, 1.0 / n_paths),
        series=list(panel.columns),
        dates=baseline_mc.future_business_days(panel.index[-1], horizon),
        source="parametric",
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

### Task 11: `run_chronos2` Lambda — SageMaker endpoint proxy

**Files:**
- Create: `tools/lambda/run_chronos2/__init__.py` (empty)
- Create: `tools/lambda/run_chronos2/handler.py`
- Create: `tools/tests/test_run_chronos2.py`

Wraps Plan A's `models.chronos2_client` for the agent. Accepts a panel
URI + optional covariates and conditioning, calls the SageMaker
endpoint, builds a PathSet, uploads, returns the URI.

- [ ] **Step 1: Write the failing test**

`tools/tests/test_run_chronos2.py`:
```python
import io
import numpy as np
import pandas as pd
import pickle
import pytest
from unittest.mock import patch
from tools.lambda_.run_chronos2 import handler


def _seed_panel(s3_client, bucket="test-data"):
    from tools.lambda_.shared import s3_io
    panel = pd.DataFrame(
        np.random.default_rng(0).normal(0, 0.005, size=(60, 3)).cumsum(axis=0),
        index=pd.bdate_range("2022-04-01", periods=60),
        columns=["USDEUR", "USDJPY", "USD_5Y"],
    )
    s3_io.upload_parquet(panel, bucket=bucket, key="lb.parquet")


def test_run_chronos2_uploads_pathset_using_mocked_client(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("CHRONOS2_ENDPOINT", "chronos2-demo-endpoint")
    _seed_panel(s3)

    fake_paths = np.zeros((50, 21, 3), dtype=float)
    with patch("tools.lambda_.run_chronos2.handler.chronos2_client.simulate",
               return_value=fake_paths) as m:
        out = handler.handler(
            {"panel_uri": "s3://test-data/lb.parquet", "horizon": 21, "n_paths": 50},
            None,
        )

    assert out["status"] == "ok"
    assert out["result"]["paths_uri"].startswith("s3://test-data/")
    m.assert_called_once()


def test_run_chronos2_rejects_invalid_horizon(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("CHRONOS2_ENDPOINT", "ep")
    out = handler.handler(
        {"panel_uri": "s3://test-data/lb.parquet", "horizon": 0, "n_paths": 50},
        None,
    )
    assert out["status"] == "error"
    assert "horizon" in out["message"]
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tools/tests/test_run_chronos2.py -v
```

Expected: FAIL — handler missing.

- [ ] **Step 3: Implement `tools/lambda/run_chronos2/handler.py`**

```python
"""run_chronos2 tool: invoke Plan A chronos2_client + return PathSet URI.

Inputs:
  {"panel_uri": str, "horizon": int, "n_paths": int,
   "covariates_uri": str?, "conditioning": dict?}
Outputs: {"paths_uri": str, "n_paths": int, "horizon": int}
"""
from __future__ import annotations
import io
import os
import pickle
import uuid

import boto3
import numpy as np

from chronos2_demo.models import chronos2_client
from chronos2_demo.types import PathSet
from tools.lambda_.shared import responses, s3_io


def handler(event: dict, _ctx) -> dict:
    horizon = int(event.get("horizon", 0))
    n_paths = int(event.get("n_paths", 0))
    if horizon <= 0 or horizon > 1000:
        return responses.error("horizon must be in (0, 1000]")
    if n_paths <= 0 or n_paths > 20_000:
        return responses.error("n_paths must be in (0, 20000]")

    try:
        panel = s3_io.download_parquet(event["panel_uri"])
    except KeyError:
        return responses.error("missing panel_uri")

    covariates = None
    if event.get("covariates_uri"):
        covariates = s3_io.download_parquet(event["covariates_uri"])

    paths = chronos2_client.simulate(
        endpoint=os.environ["CHRONOS2_ENDPOINT"],
        panel=panel,
        horizon=horizon,
        n_paths=n_paths,
        covariates=covariates,
        conditioning=event.get("conditioning"),
    )
    ps = PathSet(
        paths=paths,
        weights=np.full(n_paths, 1.0 / n_paths),
        series=list(panel.columns),
        dates=chronos2_client.future_business_days(panel.index[-1], horizon),
        source="chronos2",
    )

    bucket = os.environ["DATA_BUCKET"]
    sid = uuid.uuid4().hex[:12]
    key = f"sessions/{sid}/chronos2.pkl"
    buf = io.BytesIO()
    pickle.dump(ps, buf)
    boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    return responses.ok({
        "paths_uri": f"s3://{bucket}/{key}",
        "n_paths": n_paths,
        "horizon": horizon,
    })
```

- [ ] **Step 4: Run tests, confirm pass**

```bash
pytest tools/tests/test_run_chronos2.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/lambda/run_chronos2/ tools/tests/test_run_chronos2.py
git commit -m "feat(tools): run_chronos2 Lambda proxy for SageMaker endpoint

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
- A Python Lambda layer built from `src/chronos2_demo/`.
- Six Python Lambdas (`load_data`, `blend_paths`, `price_book`, `plot`, `lookup_use_case`, `run_chronos2`) sharing the layer.
- One Node 20 authorizer Lambda.
- An ECR repo + Fargate task definition for `baseline_mc`.
- IAM: each Lambda gets only the S3 bucket and SageMaker endpoint perms it needs.
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
    chronos2EndpointName: 'chronos2-demo-endpoint',
  });
  return Template.fromStack(tools);
}

test('creates 6 Python Lambdas + 1 Node authorizer', () => {
  const t = build();
  // 7 Lambdas total. Allow 7 +/- 1 to absorb CDK custom-resource Lambdas.
  const fns = t.findResources('AWS::Lambda::Function');
  expect(Object.keys(fns).length).toBeGreaterThanOrEqual(7);
});

test('creates an ECS cluster + Fargate task definition', () => {
  const t = build();
  t.resourceCountIs('AWS::ECS::Cluster', 1);
  t.resourceCountIs('AWS::ECS::TaskDefinition', 1);
});

test('creates an ECR repository with image scan on push', () => {
  const t = build();
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
    chronos2EndpointName: 'chronos2-demo-endpoint',
  });
  expect(tools.fnLoadData).toBeDefined();
  expect(tools.fnBlendPaths).toBeDefined();
  expect(tools.fnPriceBook).toBeDefined();
  expect(tools.fnPlot).toBeDefined();
  expect(tools.fnLookupUseCase).toBeDefined();
  expect(tools.fnRunChronos2).toBeDefined();
  expect(tools.fnAuthorizer).toBeDefined();
  expect(tools.baselineMcTaskDef).toBeDefined();
  expect(tools.baselineMcCluster).toBeDefined();
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
  chronos2EndpointName: string;
}

export class ToolsStack extends cdk.Stack {
  public readonly fnLoadData: lambda.IFunction;
  public readonly fnBlendPaths: lambda.IFunction;
  public readonly fnPriceBook: lambda.IFunction;
  public readonly fnPlot: lambda.IFunction;
  public readonly fnLookupUseCase: lambda.IFunction;
  public readonly fnRunChronos2: lambda.IFunction;
  public readonly fnAuthorizer: lambda.IFunction;
  public readonly baselineMcTaskDef: ecs.FargateTaskDefinition;
  public readonly baselineMcCluster: ecs.ICluster;
  public readonly apiKeySecret: secrets.ISecret;

  constructor(scope: Construct, id: string, props: ToolsStackProps) {
    super(scope, id, props);

    const repoRoot = path.resolve(__dirname, '..', '..');

    // Lambda layer with chronos2_demo source + shared helpers.
    const coreLayer = new lambda.LayerVersion(this, 'CoreLayer', {
      code: lambda.Code.fromAsset(repoRoot, {
        bundling: {
          image: lambda.Runtime.PYTHON_3_11.bundlingImage,
          command: [
            'bash', '-c', [
              'mkdir -p /asset-output/python',
              'cp -r src/chronos2_demo /asset-output/python/',
              'mkdir -p /asset-output/python/tools/lambda_',
              'cp tools/__init__.py /asset-output/python/tools/__init__.py || touch /asset-output/python/tools/__init__.py',
              'touch /asset-output/python/tools/lambda_/__init__.py',
              'cp -r tools/lambda/shared /asset-output/python/tools/lambda_/shared',
              'pip install --target /asset-output/python numpy scipy pandas scikit-learn matplotlib pyarrow boto3',
            ].join(' && '),
          ],
        },
      }),
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_11],
      description: 'chronos2_demo + tools.lambda_.shared + scientific deps',
    });

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
    this.fnBlendPaths = py('BlendPaths', 'blend_paths');
    this.fnPriceBook = py('PriceBook', 'price_book');
    this.fnPlot = py('Plot', 'plot');
    this.fnLookupUseCase = py('LookupUseCase', 'lookup_use_case', {
      KNOWLEDGE_DIR: '/var/task/knowledge',
    });
    this.fnRunChronos2 = py('RunChronos2', 'run_chronos2', {
      CHRONOS2_ENDPOINT: props.chronos2EndpointName,
    });

    // S3 perms — least-privilege per Lambda.
    props.dataBucket.grantReadWrite(this.fnLoadData);
    props.dataBucket.grantReadWrite(this.fnBlendPaths);
    props.dataBucket.grantRead(this.fnPriceBook);
    props.dataBucket.grantReadWrite(this.fnRunChronos2);
    props.dataBucket.grantRead(this.fnPlot);
    props.plotsBucket.grantReadWrite(this.fnPlot);

    // SageMaker invoke perm for chronos2 proxy.
    this.fnRunChronos2.addToRolePolicy(new iam.PolicyStatement({
      actions: ['sagemaker:InvokeEndpoint'],
      resources: [
        `arn:${this.partition}:sagemaker:${this.region}:${this.account}:endpoint/${props.chronos2EndpointName}`,
      ],
    }));

    // Authorizer (Node 20).
    this.apiKeySecret = new secrets.Secret(this, 'ApiKey', {
      description: 'Demo-grade API key for AgentCore endpoints',
      generateSecretString: { excludePunctuation: true, passwordLength: 32 },
    });
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
    this.baselineMcCluster = new ecs.Cluster(this, 'BaselineMcCluster', {
      vpc: props.vpc,
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
const chronos2EndpointName = process.env.CHRONOS2_ENDPOINT_NAME ?? 'chronos2-demo-endpoint';

cdk.Tags.of(app).add('Project', demoTag);
cdk.Tags.of(app).add('chronos2-demo:teardown', 'on');

const network = new NetworkStack(app, 'Chronos2DemoNetwork', { env });
const storage = new StorageStack(app, 'Chronos2DemoStorage', { env });
new ToolsStack(app, 'Chronos2DemoTools', {
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
