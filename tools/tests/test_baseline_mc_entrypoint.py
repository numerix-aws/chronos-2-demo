import importlib
import io
import pickle
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from chronos2_demo.run_spec import PROFILE, RunSpec, compute_spec_hash
from chronos2_demo.types import PathSet
from tools.lambda_.shared import s3_io


ENTRY_DIR = Path(__file__).resolve().parents[1] / "fargate" / "baseline_mc"
PROVENANCE = {
    "market_snapshot_id": "market-v1",
    "market_sha256": "a" * 64,
    "covariate_snapshot_id": "covariates-v1",
    "covariate_sha256": "b" * 64,
    "chronos_endpoint": "chronos2-demo",
    "baseline_image_digest": "sha256:baseline",
    "chronos_image_digest": "sha256:chronos",
    "agent_image_digest": "sha256:agent",
    "book_version": "cross_asset_demo_v1",
    "blend_version": "importance_weight_v1",
    "pricing_version": "cross_asset_v1",
    "tool_bundle_version": "git:test",
    "strands_version": "1.30.0",
}


def _load_entrypoint():
    sys.path.insert(0, str(ENTRY_DIR))
    sys.modules.pop("entrypoint", None)
    import entrypoint

    return importlib.reload(entrypoint)


def _stage_run(monkeypatch):
    payload = {**PROFILE, "provenance": PROVENANCE}
    spec = RunSpec(
        **payload,
        spec_hash=compute_spec_hash(payload),
        execution_id="run-1",
    )
    s3_io.upload_json(
        spec.__dict__, bucket="test-data", key="runs/run-1/run_spec.json"
    )
    panel = pd.DataFrame(
        np.random.default_rng(0).normal(size=(1260, 3)),
        index=pd.bdate_range(end=spec.as_of_date, periods=1260),
        columns=["USDEUR", "USDJPY", "USD_5Y"],
    )
    s3_io.upload_parquet(panel, bucket="test-data", key="runs/run-1/panel.parquet")
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("EXECUTION_ID", spec.execution_id)
    monkeypatch.setenv("SPEC_HASH", spec.spec_hash)
    monkeypatch.setenv("PANEL_URI", "s3://test-data/runs/run-1/panel.parquet")
    monkeypatch.setenv("OUTPUT_URI", "s3://test-data/runs/run-1/baseline.pkl")
    monkeypatch.setenv("AS_OF", spec.as_of_date)
    monkeypatch.setenv("HORIZON", str(spec.horizon))
    monkeypatch.setenv("N_PATHS", str(spec.n_paths))
    monkeypatch.setenv("N_COMPONENTS", str(spec.baseline_components))
    monkeypatch.setenv("SEED", str(spec.baseline_seed))
    monkeypatch.setenv("PRODUCER_VERSION", PROVENANCE["baseline_image_digest"])
    return spec, panel


def test_entrypoint_uses_full_staged_panel_and_writes_exact_byte_sidecar(s3, monkeypatch):
    spec, panel = _stage_run(monkeypatch)
    fake_pathset = PathSet(
        paths=np.zeros((2, 2, 3)),
        weights=np.full(2, 0.5),
        series=list(panel.columns),
        dates=pd.bdate_range("2022-10-03", periods=2),
        source="parametric",
    )
    entrypoint = _load_entrypoint()

    with patch.object(
        entrypoint.baseline_mc, "simulate_baseline", return_value=fake_pathset
    ) as simulate:
        output_uri = entrypoint.main()

    assert output_uri == "s3://test-data/runs/run-1/baseline.pkl"
    _, kwargs = simulate.call_args
    pd.testing.assert_frame_equal(kwargs["panel"], panel, check_freq=False)
    assert len(kwargs["panel"]) == 1260
    assert kwargs == {
        "panel": kwargs["panel"],
        "as_of": spec.as_of_date,
        "horizon": 252,
        "n_paths": 500,
        "n_components": 5,
        "seed": 0,
    }

    raw = s3_io.download_bytes(output_uri)
    assert pickle.load(io.BytesIO(raw)).source == "parametric"
    meta = s3_io.download_json("s3://test-data/runs/run-1/baseline.meta.json")
    assert meta == {
        "artifact_kind": "pathset",
        "artifact_sha256": s3_io.sha256_bytes(raw),
        "artifact_uri": output_uri,
        "execution_id": "run-1",
        "producer_version": "sha256:baseline",
        "scenario_role": "baseline",
        "source": "parametric",
        "spec_hash": spec.spec_hash,
    }
