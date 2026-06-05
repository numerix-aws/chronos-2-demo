"""Upload the curated demo panel (panel/covariates/regimes) to the S3 data bucket.

The deployed Lambda tools (load_data) read these from the bucket. Run after
scripts/snapshot_data.py has written data/curated/*.parquet.

Usage:
  python scripts/seed_demo_data.py --data-bucket <DataBucket-name>
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

import boto3

_FILES = ["panel.parquet", "covariates.parquet", "regimes.parquet"]


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data-bucket", required=True)
    p.add_argument("--curated-dir", default="data/curated")
    args = p.parse_args(argv)

    s3 = boto3.client("s3")
    curated = Path(args.curated_dir)
    for name in _FILES:
        body = (curated / name).read_bytes()
        s3.put_object(Bucket=args.data_bucket, Key=name, Body=body)
        print(f"uploaded s3://{args.data_bucket}/{name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
