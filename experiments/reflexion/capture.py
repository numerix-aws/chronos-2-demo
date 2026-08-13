"""One-time fixture capture: assemble the interpreter's workflow dict from S3 run artifacts.

Usage: python capture.py --bucket <DATA_BUCKET> --execution-id <eid> --out fixtures/happy_path.json
List candidate runs first:  aws s3 ls s3://<DATA_BUCKET>/runs/
"""
import argparse
import json

import boto3

ROLES = ("baseline", "chronos_only", "augmented")


def _get_json(s3, bucket: str, key: str) -> dict:
    return json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())


def assemble_fixture(bucket: str, execution_id: str, s3) -> dict:
    prefix = f"runs/{execution_id}"
    run_spec = _get_json(s3, bucket, f"{prefix}/run_spec.json")
    exposure = {}
    for role in ROLES:
        key = f"{prefix}/metrics/{role}.json"
        payload = _get_json(s3, bucket, key)
        payload["metrics_uri"] = f"s3://{bucket}/{key}"
        exposure[role] = payload
    diagnostics = _get_json(s3, bucket, f"{prefix}/diagnostics.json")
    return {
        "scenario_hint": "happy_path",
        "expected_posture": "full",
        "defect": None,
        "workflow": {
            "run_spec": run_spec,
            "exposure": exposure,
            "diagnostics": diagnostics,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--scenario-hint", default="happy_path")
    args = parser.parse_args()
    fixture = assemble_fixture(args.bucket, args.execution_id, boto3.client("s3"))
    fixture["scenario_hint"] = args.scenario_hint
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(fixture, fh, sort_keys=True, indent=2, allow_nan=False)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
