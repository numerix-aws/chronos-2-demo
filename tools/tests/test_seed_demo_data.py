import importlib.util
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "seed_demo_data", _REPO / "scripts" / "seed_demo_data.py")
seed = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(seed)


def test_seed_uploads_three_parquets(s3, tmp_path):
    for name in ("panel", "covariates", "regimes"):
        pd.DataFrame({"a": [1.0, 2.0]}).to_parquet(tmp_path / f"{name}.parquet")
    rc = seed.main(["--data-bucket", "test-data", "--curated-dir", str(tmp_path)])
    assert rc == 0
    for name in ("panel", "covariates", "regimes"):
        s3.head_object(Bucket="test-data", Key=f"{name}.parquet")  # raises if missing
