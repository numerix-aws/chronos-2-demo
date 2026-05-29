import pytest
from chronos2_demo.infra import sagemaker_endpoint as se


def test_endpoint_config_defaults_for_demo():
    cfg = se.build_endpoint_config(model_name="chronos2-demo")
    assert cfg["instance_type"].startswith("ml.g5.")
    assert cfg["initial_instance_count"] == 1
    assert "Project" in dict(cfg["tags"])
    assert dict(cfg["tags"])["Project"] == "chronos2-demo"


def test_endpoint_config_overrides_apply():
    cfg = se.build_endpoint_config(
        model_name="chronos2-demo",
        instance_type="ml.g5.2xlarge",
        extra_tags={"Owner": "muffadal"},
    )
    assert cfg["instance_type"] == "ml.g5.2xlarge"
    assert dict(cfg["tags"])["Owner"] == "muffadal"
