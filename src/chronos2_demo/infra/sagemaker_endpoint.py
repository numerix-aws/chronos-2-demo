"""SageMaker real-time endpoint orchestration for Chronos-2.

Deploy + teardown is exercised manually via scripts/deploy_chronos2_endpoint.py.
The pure config builders here are unit-tested.
"""
from __future__ import annotations
from typing import Any


def build_endpoint_config(
    model_name: str,
    instance_type: str = "ml.g5.xlarge",
    initial_instance_count: int = 1,
    extra_tags: dict[str, str] | None = None,
) -> dict[str, Any]:
    tags = [{"Key": "Project", "Value": "chronos2-demo"},
            {"Key": "ModelName", "Value": model_name}]
    if extra_tags:
        tags += [{"Key": k, "Value": v} for k, v in extra_tags.items()]
    return {
        "model_name": model_name,
        "instance_type": instance_type,
        "initial_instance_count": initial_instance_count,
        "tags": [(t["Key"], t["Value"]) for t in tags],
    }
