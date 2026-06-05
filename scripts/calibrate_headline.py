"""Measure the GENUINE headline PFE delta against the real Chronos-2 endpoint.

Writes docs/results/headline_calibration.json. Non-test, deploy-gated: needs a
live AutoGluon endpoint and the curated snapshot (scripts/snapshot_data.py).
The hermetic test suite never runs this; tests/test_headline_numbers.py remains
the offline plumbing guard. See spec §8.

Run: python scripts/calibrate_headline.py --endpoint-name chronos2-demo-ep \
        --as-of 2022-09-30 --stress-window 2022_rate_hike
"""
from __future__ import annotations
import argparse
import json
import subprocess
from datetime import datetime, timezone

import pandas as pd

from chronos2_demo import config
from chronos2_demo.augmentation import blender, regime_detector
from chronos2_demo.models import baseline_mc, chronos2_client
from chronos2_demo.infra import sagemaker_endpoint
from chronos2_demo.pricing import book as bk, exposure

OUT = config.REPO_ROOT / "docs" / "results" / "headline_calibration.json"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--endpoint-name", required=True)
    p.add_argument("--as-of", required=True)
    p.add_argument("--stress-window", required=True)
    p.add_argument("--horizon", type=int, default=config.DEFAULT_HORIZON_DAYS)
    p.add_argument("--n-paths", type=int, default=config.DEFAULT_N_PATHS)
    args = p.parse_args()

    panel = pd.read_parquet(config.DATA_CURATED / "panel.parquet")
    covariates = pd.read_parquet(config.DATA_CURATED / "covariates.parquet")
    swaps, eq, cds = bk.load_cross_asset_book(bk.DEFAULT_BOOK_PATH)

    snap = regime_detector.current_w_stress(panel, as_of=args.as_of, window=20)
    par = baseline_mc.simulate_baseline(
        panel, as_of=args.as_of, horizon=args.horizon, n_paths=args.n_paths,
        n_components=5, seed=0)

    endpoint = sagemaker_endpoint.open_endpoint(args.endpoint_name)
    client = chronos2_client.Chronos2Client(endpoint=endpoint)
    # simulate_chronos2 slices covariates to the lookback window internally, so
    # pass the full frame — it aligns cov to the sliced history index for us.
    chr_ = chronos2_client.simulate_chronos2(
        client, panel, as_of=args.as_of, horizon=args.horizon, n_paths=args.n_paths,
        covariates=covariates, lookback_days=config.DEFAULT_LOOKBACK_DAYS)

    par_term = exposure.portfolio_mtm(swaps, par, eq, cds)[:, -1]
    chr_term = exposure.portfolio_mtm(swaps, chr_, eq, cds)[:, -1]
    blended = blender.blend_paths(par, chr_, par_term, chr_term, w_stress=snap.w_stress)

    base_pfe = float(exposure.compute_metrics(
        swaps, par, equity_forwards=eq, cds_protection=cds)["pfe_975"][-1])
    aug_pfe = float(exposure.compute_metrics(
        swaps, blended, equity_forwards=eq, cds_protection=cds)["pfe_975"][-1])
    delta_usd = aug_pfe - base_pfe
    delta_pct = delta_usd / base_pfe * 100.0 if base_pfe else None

    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    artifact = {
        "status": "measured",
        "baseline_pfe_975": round(base_pfe, 2),
        "augmented_pfe_975": round(aug_pfe, 2),
        "delta_pct": round(delta_pct, 2) if delta_pct is not None else None,
        "delta_usd": round(delta_usd, 2),
        "as_of": args.as_of,
        "stress_window": args.stress_window,
        "w_stress": round(float(snap.w_stress), 4),
        "n_paths": args.n_paths,
        "endpoint_name": args.endpoint_name,
        "git_sha": sha,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    OUT.write_text(json.dumps(artifact, indent=2) + "\n")
    print(json.dumps(artifact, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
