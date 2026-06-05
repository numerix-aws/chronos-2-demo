"""Time the FM-path + closed-form pricing pipeline vs the nested-MC strawman.

Writes docs/results/latency_benchmark.json. Non-test, non-hermetic (it times
real computation). See spec §8. Nested MC is a benchmark reference only.

Run: python scripts/benchmark_latency.py [--n-paths 200] [--horizon 12] [--n-inner 200]
"""
from __future__ import annotations
import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from chronos2_demo import config
from chronos2_demo.types import PathSet
from chronos2_demo.pricing import book as bk, exposure
from chronos2_demo.models import nested_mc

OUT = config.REPO_ROOT / "docs" / "results" / "latency_benchmark.json"


def _demo_pathset(n_paths: int, horizon: int) -> PathSet:
    rng = np.random.default_rng(0)
    series = (config.FX_PAIRS
              + [f"{c}_{t}" for c in config.RATES_CCYS for t in config.RATES_TENORS]
              + config.EQUITY_INDICES + config.CREDIT_SPREADS)
    base = np.ones(len(series))
    paths = np.abs(base * (1.0 + rng.normal(0, 0.05, size=(n_paths, horizon, len(series))))) + 0.1
    return PathSet(paths=paths, weights=np.full(n_paths, 1.0 / n_paths),
                   series=series, dates=pd.bdate_range("2022-07-01", periods=horizon),
                   source="parametric")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n-paths", type=int, default=200)
    p.add_argument("--horizon", type=int, default=12)
    p.add_argument("--n-inner", type=int, default=200)
    args = p.parse_args()

    ps = _demo_pathset(args.n_paths, args.horizon)
    swaps, eq, cds = bk.load_cross_asset_book(bk.DEFAULT_BOOK_PATH)

    t0 = time.perf_counter()
    exposure.compute_pfe(exposure.portfolio_mtm(swaps, ps, eq, cds), ps.weights)
    closed_s = time.perf_counter() - t0

    t1 = time.perf_counter()
    res = nested_mc.run_nested(ps, swaps, eq, cds, n_inner=args.n_inner, inner_vol=0.01)
    nested_s = time.perf_counter() - t1

    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    artifact = {
        "status": "measured",
        "closed_form_seconds": round(closed_s, 4),
        "nested_mc_seconds": round(nested_s, 4),
        "speedup_x": round(nested_s / closed_s, 1) if closed_s > 0 else None,
        "nested_n_revaluations": res.n_revaluations,
        "n_paths": args.n_paths,
        "horizon": args.horizon,
        "n_inner": args.n_inner,
        "git_sha": sha,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    OUT.write_text(json.dumps(artifact, indent=2) + "\n")
    print(json.dumps(artifact, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
