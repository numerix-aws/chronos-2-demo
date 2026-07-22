"""Parquet + PNG helpers for tool handlers. Uses boto3."""
from __future__ import annotations
from collections.abc import Mapping
import hashlib
import io
import json

import boto3
import pandas as pd


def split_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"expected s3 URI, got {uri!r}")
    bucket, separator, key = uri[5:].partition("/")
    if not bucket or not separator or not key:
        raise ValueError(f"invalid s3 URI: {uri!r}")
    return bucket, key


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def download_bytes(uri: str) -> bytes:
    bucket, key = split_s3_uri(uri)
    return boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()


def upload_bytes(
    value: bytes,
    *,
    bucket: str,
    key: str,
    content_type: str,
) -> tuple[str, str]:
    boto3.client("s3").put_object(
        Bucket=bucket,
        Key=key,
        Body=value,
        ContentType=content_type,
    )
    return f"s3://{bucket}/{key}", sha256_bytes(value)


def download_json(uri: str) -> dict[str, object]:
    return json.loads(download_bytes(uri))


def upload_json(
    value: Mapping[str, object],
    *,
    bucket: str,
    key: str,
) -> tuple[str, str]:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return upload_bytes(
        raw,
        bucket=bucket,
        key=key,
        content_type="application/json",
    )


def upload_parquet(df: pd.DataFrame, bucket: str, key: str) -> str:
    buf = io.BytesIO()
    df.to_parquet(buf)
    buf.seek(0)
    boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    return f"s3://{bucket}/{key}"


def download_parquet(uri: str) -> pd.DataFrame:
    return pd.read_parquet(io.BytesIO(download_bytes(uri)))


def upload_png_signed(data: bytes, bucket: str, key: str, expires_in: int = 300) -> str:
    s3 = boto3.client("s3")
    s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType="image/png")
    return s3.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires_in
    )
