"""Deploy or tear down the Chronos-2 SageMaker endpoint.

Usage:
  python scripts/deploy_chronos2_endpoint.py --action deploy --model-name chronos2-demo
  python scripts/deploy_chronos2_endpoint.py --action teardown --endpoint-name chronos2-demo-ep
"""
from __future__ import annotations
import argparse
import sys

import boto3

from chronos2_demo.infra import sagemaker_endpoint as se


def deploy(args: argparse.Namespace) -> int:
    cfg = se.build_endpoint_config(
        model_name=args.model_name,
        instance_type=args.instance_type,
    )
    sm = boto3.client("sagemaker", region_name=args.region)
    endpoint_name = f"{args.model_name}-ep"
    cfg_name = f"{args.model_name}-cfg"
    sm.create_endpoint_config(
        EndpointConfigName=cfg_name,
        ProductionVariants=[{
            "VariantName": "AllTraffic",
            "ModelName": cfg["model_name"],
            "InitialInstanceCount": cfg["initial_instance_count"],
            "InstanceType": cfg["instance_type"],
        }],
        Tags=[{"Key": k, "Value": v} for k, v in cfg["tags"]],
    )
    sm.create_endpoint(EndpointName=endpoint_name, EndpointConfigName=cfg_name,
                       Tags=[{"Key": k, "Value": v} for k, v in cfg["tags"]])
    print(f"creating endpoint: {endpoint_name}")
    return 0


def teardown(args: argparse.Namespace) -> int:
    sm = boto3.client("sagemaker", region_name=args.region)
    sm.delete_endpoint(EndpointName=args.endpoint_name)
    print(f"deleted endpoint: {args.endpoint_name}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--action", choices=["deploy", "teardown"], required=True)
    p.add_argument("--model-name", default="chronos2-demo")
    p.add_argument("--endpoint-name", default="chronos2-demo-ep")
    p.add_argument("--instance-type", default="ml.g5.xlarge")
    p.add_argument("--region", default="us-east-1")
    args = p.parse_args()
    if args.action == "deploy":
        return deploy(args)
    return teardown(args)


if __name__ == "__main__":
    sys.exit(main())
