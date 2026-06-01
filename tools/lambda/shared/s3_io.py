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
