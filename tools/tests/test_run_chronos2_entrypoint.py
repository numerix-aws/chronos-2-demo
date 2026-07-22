import importlib
import io
import json
import pickle
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from chronos2_demo.run_spec import PROFILE, RunSpec, compute_spec_hash
from chronos2_demo.types import PathSet
from tools.lambda_.shared import s3_io


ENTRY_DIR = Path(__file__).resolve().parents[1] / "fargate" / "run_chronos2"
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


def _stage_run(monkeypatch, conditioning=None):
    payload = {**PROFILE, "conditioning": conditioning, "provenance": PROVENANCE}
    spec = RunSpec(
        **payload,
        spec_hash=compute_spec_hash(payload),
        execution_id="run-1",
    )
    s3_io.upload_json(
        spec.__dict__, bucket="test-data", key="runs/run-1/run_spec.json"
    )
    index = pd.bdate_range(end=spec.as_of_date, periods=1260)
    panel = pd.DataFrame(
        np.random.default_rng(0).normal(size=(1260, 3)),
        index=index,
        columns=["USDEUR", "USDJPY", "USD_5Y"],
    )
    covariates = pd.DataFrame(
        np.random.default_rng(1).normal(size=(1260, 3)),
        index=index,
        columns=["MOVE", "VIX", "WTI"],
    )
    s3_io.upload_parquet(panel, bucket="test-data", key="runs/run-1/panel.parquet")
    s3_io.upload_parquet(
        covariates, bucket="test-data", key="runs/run-1/covariates.parquet"
    )
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("EXECUTION_ID", spec.execution_id)
    monkeypatch.setenv("SPEC_HASH", spec.spec_hash)
    monkeypatch.setenv("PANEL_URI", "s3://test-data/runs/run-1/panel.parquet")
    monkeypatch.setenv(
        "COVARIATES_URI", "s3://test-data/runs/run-1/covariates.parquet"
    )
    monkeypatch.setenv("OUTPUT_URI", "s3://test-data/runs/run-1/chronos2.pkl")
    monkeypatch.setenv("AS_OF", spec.as_of_date)
    monkeypatch.setenv("CHRONOS2_ENDPOINT", PROVENANCE["chronos_endpoint"])
    monkeypatch.setenv(
        "CONDITIONING_JSON",
        json.dumps(conditioning, sort_keys=True) if conditioning else "",
    )
    monkeypatch.setenv("HORIZON", str(spec.horizon))
    monkeypatch.setenv("LOOKBACK_DAYS", str(spec.lookback_days))
    monkeypatch.setenv("N_PATHS", str(spec.n_paths))
    monkeypatch.setenv("SEED", str(spec.chronos_seed))
    monkeypatch.setenv("PRODUCER_VERSION", PROVENANCE["chronos_image_digest"])
    return spec, panel, covariates


def test_entrypoint_passes_all_manifest_inputs_and_writes_sidecar(s3, monkeypatch):
    spec, panel, covariates = _stage_run(monkeypatch)
    fake_pathset = PathSet(
        paths=np.zeros((2, 2, 3)),
        weights=np.full(2, 0.5),
        series=list(panel.columns),
        dates=pd.bdate_range("2022-10-03", periods=2),
        source="chronos2",
    )
    entrypoint = _load_entrypoint()
    endpoint = object()

    with patch.object(
        entrypoint.sagemaker_endpoint, "open_endpoint", return_value=endpoint
    ) as open_endpoint, patch.object(
        entrypoint.chronos2_client, "simulate_chronos2", return_value=fake_pathset
    ) as simulate:
        output_uri = entrypoint.main()

    assert output_uri == "s3://test-data/runs/run-1/chronos2.pkl"
    open_endpoint.assert_called_once_with("chronos2-demo")
    client = simulate.call_args.args[0]
    assert client.endpoint is endpoint
    kwargs = simulate.call_args.kwargs
    pd.testing.assert_frame_equal(kwargs["panel"], panel, check_freq=False)
    pd.testing.assert_frame_equal(kwargs["covariates"], covariates, check_freq=False)
    assert kwargs == {
        "panel": kwargs["panel"],
        "as_of": spec.as_of_date,
        "covariates": kwargs["covariates"],
        "horizon": 252,
        "n_paths": 500,
        "lookback_days": 1260,
        "conditioning": None,
        "seed": 0,
    }

    raw = s3_io.download_bytes(output_uri)
    assert pickle.load(io.BytesIO(raw)).source == "chronos2"
    meta = s3_io.download_json("s3://test-data/runs/run-1/chronos2.meta.json")
    assert meta == {
        "artifact_kind": "pathset",
        "artifact_sha256": s3_io.sha256_bytes(raw),
        "artifact_uri": output_uri,
        "execution_id": "run-1",
        "producer_version": "sha256:chronos",
        "scenario_role": "chronos_only",
        "source": "chronos2",
        "spec_hash": spec.spec_hash,
    }


def test_entrypoint_passes_manifest_conditioning(s3, monkeypatch):
    conditioning = {"series_shifts": {"USDEUR": -0.1}, "n_anchor_days": 30}
    _spec, _panel, _covariates = _stage_run(monkeypatch, conditioning)
    fake_pathset = PathSet(
        paths=np.zeros((2, 2, 3)),
        weights=np.full(2, 0.5),
        series=["USDEUR", "USDJPY", "USD_5Y"],
        dates=pd.bdate_range("2022-10-03", periods=2),
        source="chronos2_conditional",
    )
    entrypoint = _load_entrypoint()

    with patch.object(entrypoint.sagemaker_endpoint, "open_endpoint"), patch.object(
        entrypoint.chronos2_client, "simulate_chronos2", return_value=fake_pathset
    ) as simulate:
        entrypoint.main()

    parsed = simulate.call_args.kwargs["conditioning"]
    assert parsed.series_shifts == {"USDEUR": -0.1}
    assert parsed.n_anchor_days == 30
