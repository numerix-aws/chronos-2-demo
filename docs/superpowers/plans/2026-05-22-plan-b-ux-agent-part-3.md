# Plan B — Part 3: Stage 2 (continued) — Lambda Glue Tools

> **Continuation of** `2026-05-22-plan-b-ux-agent-part-2.md`. Tasks 6-9.

> **Convention reminder:** every handler returns `responses.ok(result)`
> on success and `responses.error(message)` on validation failure. The
> action-group schema in Stage 5 wraps the same envelope.

---

### Task 6: `load_data` Lambda — fetch aligned panel + regime labels

**Files:**
- Create: `tools/lambda/load_data/__init__.py` (empty)
- Create: `tools/lambda/load_data/handler.py`
- Create: `tools/tests/test_load_data.py`

The handler accepts `as_of_date` and `lookback_days`, downloads the
curated panel and regime labels from the data bucket (uploaded out of
band by Plan A's `snapshot_data.py`), slices the lookback window, and
returns an S3 URI handle.

- [ ] **Step 1: Write the failing test**

`tools/tests/test_load_data.py`:
```python
import json
import numpy as np
import pandas as pd
import pytest
from tools.lambda_.load_data import handler


def _seed_panel(s3, bucket="test-data"):
    """Seed the bucket with a panel + regime labels."""
    dates = pd.bdate_range("2022-01-03", periods=200)
    panel = pd.DataFrame(
        np.random.default_rng(0).normal(0, 0.005, size=(200, 5)).cumsum(axis=0),
        index=dates,
        columns=["USDEUR", "USDJPY", "USD_2Y", "USD_5Y", "USD_10Y"],
    )
    labels = pd.Series(np.zeros(200), index=dates, name="w_stress")
    from tools.lambda_.shared import s3_io
    s3_io.upload_parquet(panel, bucket=bucket, key="panel.parquet")
    s3_io.upload_parquet(labels.to_frame(), bucket=bucket, key="regimes.parquet")


def test_load_data_returns_s3_uri_for_lookback_slice(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    _seed_panel(s3)
    event = {"as_of_date": "2022-06-30", "lookback_days": 60}
    out = handler.handler(event, None)
    assert out["status"] == "ok"
    assert out["result"]["panel_uri"].startswith("s3://test-data/")
    assert out["result"]["regimes_uri"].startswith("s3://test-data/")
    assert out["result"]["n_rows"] == 60


def test_load_data_rejects_bad_date(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    _seed_panel(s3)
    out = handler.handler({"as_of_date": "not-a-date", "lookback_days": 60}, None)
    assert out["status"] == "error"
    assert "as_of_date" in out["message"]


def test_load_data_rejects_lookback_outside_panel(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    _seed_panel(s3)
    out = handler.handler({"as_of_date": "2010-01-01", "lookback_days": 60}, None)
    assert out["status"] == "error"
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tools/tests/test_load_data.py -v
```

Expected: FAIL — handler missing.

- [ ] **Step 3: Implement `tools/lambda/load_data/handler.py`**

```python
"""load_data tool: slice a lookback window from the curated panel.

Inputs:  {"as_of_date": "YYYY-MM-DD", "lookback_days": int}
Outputs: {"panel_uri": str, "regimes_uri": str, "n_rows": int}
"""
from __future__ import annotations
import os
import uuid
from datetime import datetime

import pandas as pd

from tools.lambda_.shared import responses, s3_io


def handler(event: dict, _ctx) -> dict:
    try:
        as_of = datetime.fromisoformat(event["as_of_date"])
    except (KeyError, ValueError) as e:
        return responses.error(f"as_of_date invalid: {e}")
    lookback = int(event.get("lookback_days", 60))
    if lookback <= 0 or lookback > 5000:
        return responses.error("lookback_days must be in (0, 5000]")

    bucket = os.environ["DATA_BUCKET"]
    panel = s3_io.download_parquet(f"s3://{bucket}/panel.parquet")
    regimes = s3_io.download_parquet(f"s3://{bucket}/regimes.parquet")

    panel.index = pd.DatetimeIndex(panel.index)
    regimes.index = pd.DatetimeIndex(regimes.index)
    end = pd.Timestamp(as_of)
    if end < panel.index.min() or end > panel.index.max():
        return responses.error(
            f"as_of_date {as_of.date()} outside panel range "
            f"[{panel.index.min().date()}, {panel.index.max().date()}]"
        )

    sliced = panel.loc[:end].tail(lookback)
    sliced_r = regimes.loc[sliced.index]
    if len(sliced) < lookback:
        return responses.error(
            f"only {len(sliced)} rows available before {as_of.date()}, "
            f"need {lookback}"
        )

    sid = uuid.uuid4().hex[:12]
    panel_key = f"sessions/{sid}/panel.parquet"
    regimes_key = f"sessions/{sid}/regimes.parquet"
    panel_uri = s3_io.upload_parquet(sliced, bucket=bucket, key=panel_key)
    regimes_uri = s3_io.upload_parquet(sliced_r, bucket=bucket, key=regimes_key)
    return responses.ok({
        "panel_uri": panel_uri,
        "regimes_uri": regimes_uri,
        "n_rows": int(len(sliced)),
    })
```

- [ ] **Step 4: Run tests, confirm pass**

```bash
pytest tools/tests/test_load_data.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/lambda/load_data/ tools/tests/test_load_data.py
git commit -m "feat(tools): load_data Lambda — lookback slice from curated panel

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: `blend_paths` Lambda — wraps `chronos2_demo.augmentation`

**Files:**
- Create: `tools/lambda/blend_paths/__init__.py` (empty)
- Create: `tools/lambda/blend_paths/handler.py`
- Create: `tools/tests/test_blend_paths.py`

This is a thin Lambda wrapper around Plan A's `augmentation.blender`.
It downloads two PathSet handles (parametric + chronos2), runs the
blender, uploads the resulting blended PathSet, and returns the URI.

- [ ] **Step 1: Write the failing test**

`tools/tests/test_blend_paths.py`:
```python
import io
import numpy as np
import pandas as pd
import pickle
import pytest
from tools.lambda_.blend_paths import handler
from chronos2_demo.types import PathSet


def _seed_pathset(s3_client, bucket, key, n_paths=100, horizon=10, n_series=3, seed=0):
    rng = np.random.default_rng(seed)
    ps = PathSet(
        paths=rng.normal(1.0, 0.05, size=(n_paths, horizon, n_series)),
        weights=np.full(n_paths, 1.0 / n_paths),
        series=[f"S{i}" for i in range(n_series)],
        dates=pd.bdate_range("2022-07-01", periods=horizon),
        source="parametric",
    )
    buf = io.BytesIO()
    pickle.dump(ps, buf)
    s3_client.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    return f"s3://{bucket}/{key}"


def test_blend_paths_returns_blended_uri(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    para_uri = _seed_pathset(s3, "test-data", "para.pkl", seed=0)
    chr_uri = _seed_pathset(s3, "test-data", "chr.pkl", seed=1)
    out = handler.handler(
        {"parametric_uri": para_uri, "chronos2_uri": chr_uri, "w_stress": 0.7},
        None,
    )
    assert out["status"] == "ok"
    assert out["result"]["blended_uri"].startswith("s3://test-data/")
    assert 0.0 <= out["result"]["w_stress"] <= 1.0


def test_blend_paths_rejects_w_stress_out_of_range(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    para_uri = _seed_pathset(s3, "test-data", "p.pkl")
    chr_uri = _seed_pathset(s3, "test-data", "c.pkl")
    out = handler.handler(
        {"parametric_uri": para_uri, "chronos2_uri": chr_uri, "w_stress": 1.5},
        None,
    )
    assert out["status"] == "error"
    assert "w_stress" in out["message"]
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tools/tests/test_blend_paths.py -v
```

Expected: FAIL — handler missing.

- [ ] **Step 3: Implement `tools/lambda/blend_paths/handler.py`**

```python
"""blend_paths tool: importance-blend parametric + Chronos-2 path sets.

Inputs:  {"parametric_uri": str, "chronos2_uri": str, "w_stress": float}
Outputs: {"blended_uri": str, "w_stress": float, "n_paths": int}
"""
from __future__ import annotations
import io
import os
import pickle
import uuid

import boto3

from chronos2_demo.augmentation import blender
from tools.lambda_.shared import responses


def _download_pickle(uri: str):
    bucket, _, key = uri[len("s3://"):].partition("/")
    obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
    return pickle.load(io.BytesIO(obj["Body"].read()))


def _upload_pickle(obj, bucket: str, key: str) -> str:
    buf = io.BytesIO()
    pickle.dump(obj, buf)
    boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    return f"s3://{bucket}/{key}"


def handler(event: dict, _ctx) -> dict:
    try:
        w_stress = float(event["w_stress"])
    except (KeyError, ValueError, TypeError) as e:
        return responses.error(f"w_stress invalid: {e}")
    if not 0.0 <= w_stress <= 1.0:
        return responses.error("w_stress must be in [0, 1]")

    try:
        para = _download_pickle(event["parametric_uri"])
        chr2 = _download_pickle(event["chronos2_uri"])
    except KeyError as e:
        return responses.error(f"missing input uri: {e}")

    blended = blender.blend(para, chr2, w_stress=w_stress)

    bucket = os.environ["DATA_BUCKET"]
    sid = uuid.uuid4().hex[:12]
    uri = _upload_pickle(blended, bucket=bucket, key=f"sessions/{sid}/blended.pkl")
    return responses.ok({
        "blended_uri": uri,
        "w_stress": w_stress,
        "n_paths": int(blended.paths.shape[0]),
    })
```

- [ ] **Step 4: Run tests, confirm pass**

```bash
pytest tools/tests/test_blend_paths.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/lambda/blend_paths/ tools/tests/test_blend_paths.py
git commit -m "feat(tools): blend_paths Lambda wrapping augmentation.blender

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 8: `price_book` Lambda — wraps `chronos2_demo.pricing`

**Files:**
- Create: `tools/lambda/price_book/__init__.py` (empty)
- Create: `tools/lambda/price_book/handler.py`
- Create: `tools/tests/test_price_book.py`

Loads a PathSet from S3, runs the XCCY book valuation (Plan A
`pricing.book` + `pricing.xccy` + `pricing.exposure`), returns a
JSON-serializable EE / PFE@97.5% / ES@97.5% summary plus per-time-bucket
arrays.

- [ ] **Step 1: Write the failing test**

`tools/tests/test_price_book.py`:
```python
import io
import numpy as np
import pandas as pd
import pickle
import pytest
from tools.lambda_.price_book import handler
from chronos2_demo.types import PathSet


def _seed_pathset(s3_client, bucket, key):
    rng = np.random.default_rng(0)
    n_paths, horizon = 200, 21
    series = ["USDEUR", "USDJPY", "USD_5Y", "EUR_5Y", "JPY_5Y"]
    ps = PathSet(
        paths=rng.normal(1.0, 0.02, size=(n_paths, horizon, len(series))),
        weights=np.full(n_paths, 1.0 / n_paths),
        series=series,
        dates=pd.bdate_range("2022-07-01", periods=horizon),
        source="parametric",
    )
    buf = io.BytesIO()
    pickle.dump(ps, buf)
    s3_client.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    return f"s3://{bucket}/{key}"


def test_price_book_returns_metric_summary(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    uri = _seed_pathset(s3, "test-data", "ps.pkl")
    out = handler.handler({"paths_uri": uri, "book_id": "demo"}, None)
    assert out["status"] == "ok"
    r = out["result"]
    for k in ("ee", "pfe_975", "es_975", "dates"):
        assert k in r
    assert len(r["ee"]) == len(r["dates"]) == 21


def test_price_book_rejects_unknown_book(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    uri = _seed_pathset(s3, "test-data", "ps.pkl")
    out = handler.handler({"paths_uri": uri, "book_id": "unknown"}, None)
    assert out["status"] == "error"
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tools/tests/test_price_book.py -v
```

Expected: FAIL — handler missing.

- [ ] **Step 3: Implement `tools/lambda/price_book/handler.py`**

```python
"""price_book tool: value the demo XCCY book on a PathSet → EE/PFE/ES.

Inputs:  {"paths_uri": str, "book_id": "demo"}
Outputs: {"ee": [..], "pfe_975": [..], "es_975": [..], "dates": ["YYYY-MM-DD", ...]}
"""
from __future__ import annotations
import io
import pickle

import boto3

from chronos2_demo.pricing import book as book_mod, exposure
from tools.lambda_.shared import responses


def _download_pickle(uri: str):
    bucket, _, key = uri[len("s3://"):].partition("/")
    obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
    return pickle.load(io.BytesIO(obj["Body"].read()))


def handler(event: dict, _ctx) -> dict:
    book_id = event.get("book_id", "demo")
    if book_id != "demo":
        return responses.error(f"unknown book_id {book_id!r}; only 'demo' supported")
    try:
        ps = _download_pickle(event["paths_uri"])
    except KeyError:
        return responses.error("missing paths_uri")

    book = book_mod.demo_book()
    metrics = exposure.compute_metrics(ps, book)
    return responses.ok({
        "ee": [float(x) for x in metrics["ee"]],
        "pfe_975": [float(x) for x in metrics["pfe_975"]],
        "es_975": [float(x) for x in metrics["es_975"]],
        "dates": [d.strftime("%Y-%m-%d") for d in metrics["dates"]],
    })
```

- [ ] **Step 4: Run tests, confirm pass**

```bash
pytest tools/tests/test_price_book.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/lambda/price_book/ tools/tests/test_price_book.py
git commit -m "feat(tools): price_book Lambda — XCCY exposure on a PathSet

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 9: `plot` and `lookup_use_case` Lambdas

**Files:**
- Create: `tools/lambda/plot/__init__.py` (empty)
- Create: `tools/lambda/plot/handler.py`
- Create: `tools/lambda/lookup_use_case/__init__.py` (empty)
- Create: `tools/lambda/lookup_use_case/handler.py`
- Create: `tools/tests/test_plot.py`
- Create: `tools/tests/test_lookup_use_case.py`

`plot` accepts a `spec` (`pfe_overlay`, `path_fan`, or `regime_ribbon`)
plus referenced URIs and returns a presigned S3 PNG URL the SPA
renders inline. `lookup_use_case` reads a topic from the curated
knowledge index and returns the brief markdown plus a one-line summary.

- [ ] **Step 1: Write the failing tests**

`tools/tests/test_plot.py`:
```python
import io
import numpy as np
import pandas as pd
import pickle
import pytest
from tools.lambda_.plot import handler
from chronos2_demo.types import PathSet


def _seed_metrics(s3_client, bucket, key):
    metrics = {
        "ee": [0.0, 0.1, 0.2],
        "pfe_975": [0.0, 0.5, 1.0],
        "es_975": [0.0, 0.6, 1.2],
        "dates": ["2022-07-01", "2022-07-04", "2022-07-05"],
    }
    import json
    s3_client.put_object(
        Bucket=bucket, Key=key, Body=json.dumps(metrics).encode()
    )
    return f"s3://{bucket}/{key}"


def _seed_pathset(s3_client, bucket, key):
    rng = np.random.default_rng(0)
    ps = PathSet(
        paths=rng.normal(1.0, 0.05, size=(50, 10, 2)),
        weights=np.full(50, 1.0 / 50),
        series=["S0", "S1"],
        dates=pd.bdate_range("2022-07-01", periods=10),
        source="parametric",
    )
    buf = io.BytesIO()
    pickle.dump(ps, buf)
    s3_client.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    return f"s3://{bucket}/{key}"


def test_plot_pfe_overlay_returns_signed_uri(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("PLOTS_BUCKET", "test-plots")
    base = _seed_metrics(s3, "test-data", "b.json")
    aug = _seed_metrics(s3, "test-data", "a.json")
    out = handler.handler(
        {"spec": "pfe_overlay", "baseline_uri": base, "augmented_uri": aug,
         "title": "Test"},
        None,
    )
    assert out["status"] == "ok"
    assert out["result"]["image_uri"].startswith("https://")


def test_plot_rejects_unknown_spec(s3, monkeypatch):
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("PLOTS_BUCKET", "test-plots")
    out = handler.handler({"spec": "nope"}, None)
    assert out["status"] == "error"
```

`tools/tests/test_lookup_use_case.py`:
```python
import json
from pathlib import Path
import pytest
from tools.lambda_.lookup_use_case import handler


def test_lookup_returns_brief_for_known_topic(monkeypatch, tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("KNOWLEDGE_DIR", str(repo_root / "agent" / "knowledge"))
    out = handler.handler({"topic": "stress_test_design"}, None)
    assert out["status"] == "ok"
    assert "stress" in out["result"]["markdown"].lower()
    assert out["result"]["topic"] == "stress_test_design"


def test_lookup_lists_topics_when_no_topic_given(monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("KNOWLEDGE_DIR", str(repo_root / "agent" / "knowledge"))
    out = handler.handler({}, None)
    assert out["status"] == "ok"
    assert isinstance(out["result"]["topics"], list)
    assert "stress_test_design" in out["result"]["topics"]


def test_lookup_rejects_unknown_topic(monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("KNOWLEDGE_DIR", str(repo_root / "agent" / "knowledge"))
    out = handler.handler({"topic": "made_up"}, None)
    assert out["status"] == "error"
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tools/tests/test_plot.py tools/tests/test_lookup_use_case.py -v
```

Expected: FAIL — handlers missing.

- [ ] **Step 3: Implement `tools/lambda/plot/handler.py`**

```python
"""plot tool: render PFE overlay / path fan / regime ribbon → S3 PNG signed URL.

Inputs vary by spec:
  pfe_overlay:  {"spec": "pfe_overlay", "baseline_uri": str, "augmented_uri": str, "title": str}
  path_fan:     {"spec": "path_fan", "paths_uri": str, "series": str, "title": str}
  regime_ribbon:{"spec": "regime_ribbon", "regimes_uri": str, "threshold": float, "title": str}
Outputs: {"image_uri": str (presigned)}
"""
from __future__ import annotations
import io
import json
import os
import pickle
import uuid

import boto3
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from chronos2_demo.plotting import pfe_overlay, path_samples, regime_ribbon
from tools.lambda_.shared import responses, s3_io


def _download_json(uri: str) -> dict:
    bucket, _, key = uri[len("s3://"):].partition("/")
    obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
    return json.loads(obj["Body"].read())


def _download_pickle(uri: str):
    bucket, _, key = uri[len("s3://"):].partition("/")
    obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
    return pickle.load(io.BytesIO(obj["Body"].read()))


def _fig_to_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _publish(png: bytes) -> str:
    bucket = os.environ["PLOTS_BUCKET"]
    key = f"plots/{uuid.uuid4().hex[:12]}.png"
    return s3_io.upload_png_signed(png, bucket=bucket, key=key, expires_in=900)


def handler(event: dict, _ctx) -> dict:
    spec = event.get("spec")
    title = event.get("title", "")
    try:
        if spec == "pfe_overlay":
            base = _download_json(event["baseline_uri"])
            aug = _download_json(event["augmented_uri"])
            base["dates"] = pd.DatetimeIndex(base["dates"])
            aug["dates"] = pd.DatetimeIndex(aug["dates"])
            fig = pfe_overlay.plot_pfe_overlay(baseline=base, augmented=aug, title=title)
        elif spec == "path_fan":
            ps = _download_pickle(event["paths_uri"])
            fig = path_samples.plot_path_fan(
                ps, series=event["series"],
                n_path_samples=event.get("n_path_samples", 20),
                title=title,
            )
        elif spec == "regime_ribbon":
            r_df = _download_pickle(event["regimes_uri"]) if event["regimes_uri"].endswith(".pkl") \
                else s3_io.download_parquet(event["regimes_uri"])
            w = r_df["w_stress"] if hasattr(r_df, "columns") else r_df
            fig = regime_ribbon.plot_regime_ribbon(
                w, threshold=float(event.get("threshold", 0.7)), title=title
            )
        else:
            return responses.error(f"unknown spec {spec!r}")
    except KeyError as e:
        return responses.error(f"missing input: {e}")

    png = _fig_to_png(fig)
    return responses.ok({"image_uri": _publish(png), "spec": spec})
```

- [ ] **Step 4: Implement `tools/lambda/lookup_use_case/handler.py`**

```python
"""lookup_use_case tool: serve curated adjacent-use-case briefs.

Inputs:  {"topic": str?}            # if absent, returns list of topics
Outputs: {"topic": str, "summary": str, "markdown": str} | {"topics": [str, ...]}
"""
from __future__ import annotations
import json
import os
from pathlib import Path

from tools.lambda_.shared import responses


def _index() -> dict:
    root = Path(os.environ["KNOWLEDGE_DIR"])
    return json.loads((root / "index.json").read_text())


def handler(event: dict, _ctx) -> dict:
    idx = _index()
    topic = event.get("topic")
    if not topic:
        return responses.ok({"topics": sorted(idx.keys())})
    if topic not in idx:
        return responses.error(
            f"unknown topic {topic!r}; available: {sorted(idx.keys())}"
        )
    root = Path(os.environ["KNOWLEDGE_DIR"])
    md = (root / idx[topic]["file"]).read_text()
    return responses.ok({
        "topic": topic,
        "summary": idx[topic]["summary"],
        "markdown": md,
    })
```

- [ ] **Step 5: Run tests, confirm pass**

```bash
pytest tools/tests/test_plot.py tools/tests/test_lookup_use_case.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add tools/lambda/plot/ tools/lambda/lookup_use_case/ \
        tools/tests/test_plot.py tools/tests/test_lookup_use_case.py
git commit -m "feat(tools): plot and lookup_use_case Lambdas

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

> _Continue with `2026-05-22-plan-b-ux-agent-part-4.md` (Stages 3-4 — Fargate baseline MC, Chronos-2 proxy, tools-stack wiring, Tasks 10-13)._
