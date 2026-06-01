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
