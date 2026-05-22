# Plan B — Part 2: Stages 1-2 — Storage, Knowledge Briefs, Lambda Glue Tools

> **Continuation of** `2026-05-22-plan-b-ux-agent.md`. Tasks 3-9.

---

## Stage 1 — Storage + curated knowledge briefs

### Task 3: Storage stack — S3 buckets for panel, plots, traces

**Files:**
- Create: `infra/lib/storage-stack.ts`
- Create: `infra/test/storage-stack.test.ts`
- Modify: `infra/bin/app.ts`

Three buckets: data panel (uploaded once by Plan A's `snapshot_data.py` script), plot output (Lambda writes PNGs that the SPA reads via signed URLs), and agent traces (CloudWatch primary, S3 archive for replay).

- [ ] **Step 1: Write the failing test**

`infra/test/storage-stack.test.ts`:
```typescript
import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { StorageStack } from '../lib/storage-stack';

test('creates 3 buckets with versioning and SSE-S3', () => {
  const app = new cdk.App();
  const stack = new StorageStack(app, 'TestStorage');
  const t = Template.fromStack(stack);

  t.resourceCountIs('AWS::S3::Bucket', 3);
  t.allResourcesProperties('AWS::S3::Bucket', {
    VersioningConfiguration: { Status: 'Enabled' },
    BucketEncryption: Match.objectLike({}),
  });
});

test('plots bucket has CORS allowing GET from anywhere', () => {
  const app = new cdk.App();
  const stack = new StorageStack(app, 'TestStorage');
  const t = Template.fromStack(stack);

  t.hasResourceProperties('AWS::S3::Bucket', Match.objectLike({
    CorsConfiguration: {
      CorsRules: Match.arrayWith([
        Match.objectLike({ AllowedMethods: Match.arrayWith(['GET']) }),
      ]),
    },
  }));
});

test('exposes bucket properties', () => {
  const app = new cdk.App();
  const stack = new StorageStack(app, 'TestStorage');
  expect(stack.dataBucket).toBeDefined();
  expect(stack.plotsBucket).toBeDefined();
  expect(stack.tracesBucket).toBeDefined();
});
```

- [ ] **Step 2: Run, confirm fail**

```bash
cd infra && npm test -- storage-stack
```

Expected: FAIL — `Cannot find module '../lib/storage-stack'`.

- [ ] **Step 3: Implement `infra/lib/storage-stack.ts`**

```typescript
import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

export class StorageStack extends cdk.Stack {
  public readonly dataBucket: s3.IBucket;
  public readonly plotsBucket: s3.IBucket;
  public readonly tracesBucket: s3.IBucket;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const common: s3.BucketProps = {
      versioned: true,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    };

    this.dataBucket = new s3.Bucket(this, 'DataBucket', { ...common });

    this.plotsBucket = new s3.Bucket(this, 'PlotsBucket', {
      ...common,
      cors: [{
        allowedMethods: [s3.HttpMethods.GET],
        allowedOrigins: ['*'],
        allowedHeaders: ['*'],
        maxAge: 300,
      }],
    });

    this.tracesBucket = new s3.Bucket(this, 'TracesBucket', { ...common });
  }
}
```

- [ ] **Step 4: Wire into `infra/bin/app.ts`**

Add after the `network` line:

```typescript
import { StorageStack } from '../lib/storage-stack';

const storage = new StorageStack(app, 'Chronos2DemoStorage', { env });
```

- [ ] **Step 5: Run tests, confirm pass**

```bash
cd infra && npm test
```

Expected: 5 total passed (network + storage).

- [ ] **Step 6: Commit**

```bash
git add infra/lib/storage-stack.ts infra/test/storage-stack.test.ts infra/bin/app.ts
git commit -m "feat(infra): storage stack with data/plots/traces buckets

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: Curated knowledge briefs (§10 closing tour)

**Files:**
- Create: `agent/knowledge/stress_test_design.md`
- Create: `agent/knowledge/im_vm_forecasting.md`
- Create: `agent/knowledge/frtb_ima_es.md`
- Create: `agent/knowledge/market_data_gap_filling.md`
- Create: `agent/knowledge/scenario_limits.md`
- Create: `agent/knowledge/long_context_windows.md`
- Create: `agent/knowledge/temporal_hierarchies.md`
- Create: `agent/knowledge/index.json`
- Create: `tools/tests/test_knowledge_index.py`

Pre-authored adjacent-use-case briefs the `lookup_use_case` tool serves. Each is a short Markdown file (~150-300 words) — the agent quotes them directly. The index is the routing table.

- [ ] **Step 1: Write the failing test**

`tools/tests/test_knowledge_index.py`:
```python
"""The knowledge index must list every brief, and every listed file must exist."""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = REPO_ROOT / "agent" / "knowledge"


def test_index_lists_all_briefs():
    index = json.loads((KNOWLEDGE_DIR / "index.json").read_text())
    expected = {
        "stress_test_design",
        "im_vm_forecasting",
        "frtb_ima_es",
        "market_data_gap_filling",
        "scenario_limits",
        "long_context_windows",
        "temporal_hierarchies",
    }
    assert set(index.keys()) == expected


def test_each_indexed_brief_file_exists_and_nonempty():
    index = json.loads((KNOWLEDGE_DIR / "index.json").read_text())
    for topic, meta in index.items():
        path = KNOWLEDGE_DIR / meta["file"]
        assert path.exists(), f"missing brief file for {topic}"
        body = path.read_text().strip()
        assert len(body) > 100, f"brief {topic} is suspiciously short"


def test_each_brief_has_a_one_line_summary():
    index = json.loads((KNOWLEDGE_DIR / "index.json").read_text())
    for topic, meta in index.items():
        assert "summary" in meta and len(meta["summary"]) > 20
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tools/tests/test_knowledge_index.py -v
```

Expected: FAIL — index.json missing.

- [ ] **Step 3: Create the seven brief files**

`agent/knowledge/stress_test_design.md`:
```markdown
# Stress test design (regulatory + internal)

Time-series foundation models help two ways: scenario library curation
(which historical regimes are actually distinct?) and forward stress
construction (generate plausible but unseen joint stress paths conditioned
on macro narratives). Where parametric calibration forces a single
covariance assumption per regime, an FM samples joint paths whose
correlation structure varies path-by-path, exposing tail-coupling regimes
classical methods miss.

The Plan A "correct + reweight" pattern transfers directly: keep your
existing regulatory stress tests as the parametric anchor; let the FM
generate an augmented overlay; report sensitivity to the augmentation.
The augmented set is not the regulatory submission — it is the
challenger model that flags where the submission may be optimistic.
```

`agent/knowledge/im_vm_forecasting.md`:
```markdown
# Initial Margin / Variation Margin forecasting

IM and VM forecasts depend on quantile estimates of future P&L
distributions, conditioned on the current portfolio and on the joint
evolution of risk factors. Today these are typically driven by historical
simulation or filtered historical simulation — a path set with
no regime awareness.

A time-series FM contributes a probabilistic joint forecast keyed off
the same lookback window, with two practical advantages: covariate
awareness (VIX, MOVE, basis swap spreads) and explicit conditioning on
analyst-supplied stress narratives. The same blender + reweighter that
Plan A builds for PFE applies — IM/VM is a different read on the same
weighted path tensor.
```

`agent/knowledge/frtb_ima_es.md`:
```markdown
# FRTB IMA expected shortfall augmentation

FRTB Internal Model Approach centers on an Expected Shortfall calculation
under stress-period calibration. The challenge is that "stress period"
selection is often a backward-looking exercise picking a single window;
correlation-breakdown effects are baked into that window's empirical
covariance, with no mechanism for new regime structure.

A foundation-model overlay augments the stressed-ES path set with paths
conditioned on FM-detected current-regime features. The reweighter keeps
the regulatory ES anchor (uniform-weight historical) while shifting tail
mass toward augmented paths when the regime detector indicates stress.
This is a challenger ES, useful for internal capital adequacy oversight
even where the regulatory ES is unchanged.
```

`agent/knowledge/market_data_gap_filling.md`:
```markdown
# Market data gap-filling for stale or sparse series

Emerging-market FX, off-the-run rates, and infrequently quoted credit
spreads have stale or missing observations. Today these gaps are filled
with proxy series, last-observation-carry-forward, or PCA reconstruction
from correlated liquid factors — all of which lose information about
joint dynamics during stress windows when the proxies themselves break.

A time-series FM trained on dense markets transfers across to sparse
ones by conditioning on observable cross-asset features. Plan A's
covariate channel (VIX/MOVE/WTI) demonstrates the mechanism; the same
trick fills, e.g., a stale TRY rate using observed EUR rates, USDTRY,
and oil futures, with explicit uncertainty bands rather than a fitted
deterministic value.
```

`agent/knowledge/scenario_limits.md`:
```markdown
# Scenario-based limits monitoring

Most limit frameworks compute exposure under a small set of pre-defined
scenarios (parallel rate shifts, FX shocks). Limits breach when computed
exposure exceeds a threshold under any scenario. The framework is
auditable but blind to joint-tail combinations the predefined set does
not enumerate.

A foundation-model overlay generates a continuous scenario manifold,
weighted by the regime detector. The limit framework consumes the
weighted top-N tail paths instead of (or alongside) the predefined set.
The result: limits that adapt to current regime without manual
re-parameterization, with full traceability — every contributing path
is inspectable.
```

`agent/knowledge/long_context_windows.md`:
```markdown
# Long context windows — multi-cycle conditioning

Chronos-2's long context window admits multi-decade conditioning history
in a single forward pass — useful when the regime is not adequately
characterized by a 60-day rolling window. Examples:

- 2022 rate-hike conditioning is sharper when the model can attend to
  1994 and 1979 cycles, not just trailing 12 months.
- FX peg breaks are rare events; long-context conditioning exposes
  pre-break statistical signatures (vol-of-vol drift, basis widening)
  invisible to short-window detectors.
- Decade-spanning backtests run without rolling recalibration — the
  model is the calibration.

This capability is **not** exercised in the live demo (we use a 60-day
context window for parity with the parametric baseline); it is one of
the "what else could this enable" beats for the closing tour.
```

`agent/knowledge/temporal_hierarchies.md`:
```markdown
# Temporal hierarchies — intraday ↔ daily ↔ macro

Chronos-2 supports forecasting at multiple frequencies in one call —
intraday minute bars, daily closes, weekly macro releases — sharing a
single representation. Use cases this opens up:

- **Intraday liquidity-aware exposure**: replace the end-of-day PFE
  approximation with intraday-aware paths that respect when liquidity
  windows close.
- **Vol-surface forecasting at multiple frequencies**: short-dated
  options driven by intraday flow, long-dated by macro conditioning,
  one consistent forecast.
- **Event-window risk (FOMC, NFP)**: condition on calendar features
  the parametric stack doesn't see; produce event-windowed PFE
  alongside the regular curve.

Like long context, this is a tour beat — not in the live demo, but
named so the audience can recognize where the same deployment pattern
extends.
```

`agent/knowledge/scenario_limits.md` is repeated above; ensure all seven distinct files exist.

- [ ] **Step 4: Create `agent/knowledge/index.json`**

```json
{
  "stress_test_design": {
    "file": "stress_test_design.md",
    "summary": "Augment regulatory and internal stress tests with FM-generated regime-aware overlays."
  },
  "im_vm_forecasting": {
    "file": "im_vm_forecasting.md",
    "summary": "Apply correct+reweight to IM/VM forecasting via joint probabilistic paths with covariate conditioning."
  },
  "frtb_ima_es": {
    "file": "frtb_ima_es.md",
    "summary": "Build a challenger ES alongside FRTB IMA stressed-ES using FM-augmented tail paths."
  },
  "market_data_gap_filling": {
    "file": "market_data_gap_filling.md",
    "summary": "Fill stale or sparse market series with FM conditioning on observable cross-asset features."
  },
  "scenario_limits": {
    "file": "scenario_limits.md",
    "summary": "Replace fixed predefined scenarios with continuous regime-weighted FM scenario manifolds for limits."
  },
  "long_context_windows": {
    "file": "long_context_windows.md",
    "summary": "Use multi-decade conditioning history for regime characterization beyond rolling windows."
  },
  "temporal_hierarchies": {
    "file": "temporal_hierarchies.md",
    "summary": "Joint intraday/daily/macro forecasting in one model: intraday PFE, vol-surface forecasting, event windows."
  }
}
```

- [ ] **Step 5: Run tests, confirm pass**

```bash
pytest tools/tests/test_knowledge_index.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add agent/knowledge/ tools/tests/test_knowledge_index.py
git commit -m "feat(agent): curated knowledge briefs + index for closing tour

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Stage 2 — Lambda glue tools

> Convention for every tool handler: input is a JSON event with named
> string parameters (Bedrock action-group format). Output is a JSON
> envelope `{"status": "ok", "result": {...}}` or `{"status": "error",
> "message": "..."}`. The shared `responses.ok()` / `responses.error()`
> helpers enforce this.

### Task 5: Shared response envelope + S3 helpers

**Files:**
- Create: `tools/lambda/shared/__init__.py` (empty)
- Create: `tools/lambda/shared/responses.py`
- Create: `tools/lambda/shared/s3_io.py`
- Create: `tools/tests/conftest.py`
- Create: `tools/tests/test_responses.py`
- Create: `tools/tests/test_s3_io.py`

- [ ] **Step 1: Write the failing tests**

`tools/tests/conftest.py`:
```python
"""Shared pytest fixtures for Lambda handler tests."""
import os
import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def aws_creds(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def s3(aws_creds):
    with mock_aws():
        client = boto3.client("s3")
        client.create_bucket(Bucket="test-data")
        client.create_bucket(Bucket="test-plots")
        yield client
```

`tools/tests/test_responses.py`:
```python
from tools.lambda_.shared import responses


def test_ok_envelope_shape():
    out = responses.ok({"x": 1})
    assert out["status"] == "ok"
    assert out["result"] == {"x": 1}


def test_error_envelope_shape():
    out = responses.error("bad input")
    assert out["status"] == "error"
    assert out["message"] == "bad input"


def test_ok_round_trips_through_json():
    import json
    out = responses.ok({"arr": [1, 2, 3]})
    assert json.loads(json.dumps(out)) == out
```

`tools/tests/test_s3_io.py`:
```python
import io
import numpy as np
import pandas as pd
from tools.lambda_.shared import s3_io


def test_upload_and_download_parquet_round_trip(s3):
    df = pd.DataFrame({"a": [1, 2, 3], "b": [0.1, 0.2, 0.3]})
    uri = s3_io.upload_parquet(df, bucket="test-data", key="x.parquet")
    assert uri == "s3://test-data/x.parquet"
    out = s3_io.download_parquet(uri)
    pd.testing.assert_frame_equal(out, df)


def test_upload_png_returns_signed_uri(s3):
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    signed = s3_io.upload_png_signed(png_bytes, bucket="test-plots", key="p.png", expires_in=300)
    assert signed.startswith("https://")
    assert "test-plots" in signed
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tools/tests/test_responses.py tools/tests/test_s3_io.py -v
```

Expected: FAIL — modules missing.

> Note: the test imports use `tools.lambda_.shared` because `lambda` is a
> Python keyword. To support that, we add `__init__.py` files such that
> the package import works. Step 3 creates the directory shim.

- [ ] **Step 3: Create the package shim**

`tools/__init__.py`: empty.
`tools/lambda_/__init__.py`: empty (note trailing underscore to avoid Python keyword).
`tools/lambda_/shared/__init__.py`: empty.

> The Lambda runtime imports the handler from `tools/lambda/<name>/handler.py`
> directly (the directory name on disk uses `lambda` so packagers and
> CDK constructs find it idiomatically). The test-only `tools/lambda_/`
> shim re-exports `shared`. The CDK Lambda asset path uses
> `tools/lambda/shared/`. We sync the two with a single `conftest.py`
> sys.path tweak.

Replace `tools/tests/conftest.py` (created in Step 1) with the augmented version below:

```python
"""Shared pytest fixtures for Lambda handler tests."""
import os
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

# Map physical `tools/lambda/` dir to importable `tools.lambda_` package.
_REPO = Path(__file__).resolve().parents[2]
_LAMBDA_DIR = _REPO / "tools" / "lambda"
sys.path.insert(0, str(_REPO))

# Make `import tools.lambda_.shared.responses` resolve to tools/lambda/shared/responses.py
import importlib
import types

if "tools" not in sys.modules:
    tools_pkg = types.ModuleType("tools")
    tools_pkg.__path__ = [str(_REPO / "tools")]
    sys.modules["tools"] = tools_pkg

lambda_pkg = types.ModuleType("tools.lambda_")
lambda_pkg.__path__ = [str(_LAMBDA_DIR)]
sys.modules["tools.lambda_"] = lambda_pkg


@pytest.fixture
def aws_creds(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def s3(aws_creds):
    with mock_aws():
        client = boto3.client("s3")
        client.create_bucket(Bucket="test-data")
        client.create_bucket(Bucket="test-plots")
        yield client
```

- [ ] **Step 4: Implement `tools/lambda/shared/responses.py`**

```python
"""JSON response envelope for Lambda tool handlers."""


def ok(result: dict) -> dict:
    return {"status": "ok", "result": result}


def error(message: str) -> dict:
    return {"status": "error", "message": message}
```

- [ ] **Step 5: Implement `tools/lambda/shared/s3_io.py`**

```python
"""Parquet + PNG helpers for tool handlers. Uses boto3."""
from __future__ import annotations
import io
import boto3
import pandas as pd


def upload_parquet(df: pd.DataFrame, bucket: str, key: str) -> str:
    buf = io.BytesIO()
    df.to_parquet(buf)
    buf.seek(0)
    boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    return f"s3://{bucket}/{key}"


def download_parquet(uri: str) -> pd.DataFrame:
    assert uri.startswith("s3://"), f"expected s3://, got {uri}"
    bucket, _, key = uri[len("s3://"):].partition("/")
    obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
    return pd.read_parquet(io.BytesIO(obj["Body"].read()))


def upload_png_signed(data: bytes, bucket: str, key: str, expires_in: int = 300) -> str:
    s3 = boto3.client("s3")
    s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType="image/png")
    return s3.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires_in
    )
```

- [ ] **Step 6: Add `moto` to dev deps**

Modify `pyproject.toml` (Plan A's). Add `"moto[s3]>=5.0"` to `[project.optional-dependencies] dev`:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=4.1",
    "jupyterlab>=4.0",
    "ipykernel>=6.29",
    "moto[s3]>=5.0",
]
```

Reinstall:
```bash
pip install -e ".[dev]"
```

- [ ] **Step 7: Run tests, confirm pass**

```bash
pytest tools/tests/test_responses.py tools/tests/test_s3_io.py -v
```

Expected: 5 passed.

- [ ] **Step 8: Commit**

```bash
git add tools/__init__.py tools/lambda_/__init__.py \
        tools/lambda/shared/ \
        tools/tests/conftest.py tools/tests/test_responses.py tools/tests/test_s3_io.py \
        pyproject.toml
git commit -m "feat(tools): shared response envelope + S3 IO helpers

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

> _Continue with `2026-05-22-plan-b-ux-agent-part-3.md` (Tasks 6-9 — load_data, blend_paths, price_book, plot, lookup_use_case)._
