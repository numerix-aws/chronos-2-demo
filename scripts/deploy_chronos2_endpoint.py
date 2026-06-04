"""Deploy or tear down the Chronos-2 endpoint via AutoGluon Cloud.

Requires the `deploy` extra: pip install -e ".[deploy]".

Usage:
  python scripts/deploy_chronos2_endpoint.py --action deploy \\
      --cache-uri s3://YOUR-BUCKET/fm-cache
  python scripts/deploy_chronos2_endpoint.py --action deploy --mode realtime
  python scripts/deploy_chronos2_endpoint.py --action teardown
"""
from __future__ import annotations
import argparse
import sys

from chronos2_demo.infra import sagemaker_endpoint as se


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--action", choices=["deploy", "teardown"], required=True)
    p.add_argument("--endpoint-name", default=se.DEFAULT_ENDPOINT_NAME)
    p.add_argument("--mode", choices=["serverless", "realtime"], default=se.DEFAULT_MODE)
    p.add_argument("--instance-type", default=se.DEFAULT_INSTANCE_TYPE,
                   help="GPU instance for --mode realtime")
    p.add_argument("--cache-uri", default=None,
                   help="S3 URI for the cached model artifact (required for serverless)")
    args = p.parse_args()
    if args.action == "deploy":
        if args.mode == "serverless" and not args.cache_uri:
            p.error("--cache-uri is required for serverless deploys")
        name = se.deploy_demo_endpoint(
            endpoint_name=args.endpoint_name,
            mode=args.mode,
            instance_type=args.instance_type,
            cache_uri=args.cache_uri,
        )
        print(f"deployed endpoint: {name}")
    else:
        se.delete_demo_endpoint(endpoint_name=args.endpoint_name)
        print(f"deleted endpoint: {args.endpoint_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
