import io
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
from tools.lambda_.shared import s3_io


def test_json_helpers_import_without_pandas():
    repo_root = Path(__file__).resolve().parents[2]
    lambda_dir = repo_root / "tools" / "lambda"
    script = f"""
import builtins
import sys
import types

lambda_pkg = types.ModuleType("tools.lambda_")
lambda_pkg.__path__ = [{str(lambda_dir)!r}]
sys.modules["tools.lambda_"] = lambda_pkg

real_import = builtins.__import__
def block_pandas(name, *args, **kwargs):
    if name == "pandas" or name.startswith("pandas."):
        raise ModuleNotFoundError("pandas is not installed in the light layer")
    return real_import(name, *args, **kwargs)
builtins.__import__ = block_pandas

from tools.lambda_.shared import s3_io
assert s3_io.json_bytes({{"ok": True}}) == b'{{"ok":true}}'
"""
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )


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
