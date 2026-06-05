import boto3
import json
import pytest
from moto import mock_aws
from unittest.mock import patch, MagicMock

from tools.lambda_.run_chronos2 import handler


@pytest.fixture
def ecs_env(aws_creds, monkeypatch):
    with mock_aws():
        ec2 = boto3.client("ec2", region_name="us-east-1")
        vpc_id = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
        ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={"Value": True})
        subnet_id = ec2.create_subnet(
            VpcId=vpc_id, CidrBlock="10.0.1.0/24"
        )["Subnet"]["SubnetId"]
        sg_id = ec2.create_security_group(
            GroupName="chronos2-sg", Description="test", VpcId=vpc_id
        )["GroupId"]

        ecs = boto3.client("ecs", region_name="us-east-1")
        cluster = ecs.create_cluster(clusterName="chronos2")["cluster"]["clusterArn"]
        task_def = ecs.register_task_definition(
            family="chronos2",
            requiresCompatibilities=["FARGATE"],
            networkMode="awsvpc",
            cpu="4096",
            memory="8192",
            containerDefinitions=[{"name": "App", "image": "x", "essential": True, "memory": 8192}],
        )["taskDefinition"]["taskDefinitionArn"]
        monkeypatch.setenv("DATA_BUCKET", "test-data")
        monkeypatch.setenv("CLUSTER_ARN", cluster)
        monkeypatch.setenv("TASK_DEFINITION_ARN", task_def)
        monkeypatch.setenv("CONTAINER_NAME", "App")
        monkeypatch.setenv("SUBNET_IDS", subnet_id)
        monkeypatch.setenv("SECURITY_GROUP_IDS", sg_id)
        monkeypatch.setenv("CHRONOS2_ENDPOINT", "chronos2-demo-ep")
        yield


def test_launcher_starts_task_and_returns_handle(ecs_env):
    out = handler.handler(
        {"panel_uri": "s3://test-data/lb.parquet", "as_of": "2022-06-23",
         "horizon": 21, "n_paths": 200, "covariates_uri": "s3://test-data/cov.parquet"},
        None,
    )
    assert out["status"] == "ok"
    assert out["result"]["task_arn"]
    assert out["result"]["paths_uri"].startswith("s3://test-data/sessions/")
    assert out["result"]["paths_uri"].endswith("/chronos2.pkl")


def test_launcher_rejects_invalid_n_paths(ecs_env):
    out = handler.handler(
        {"panel_uri": "s3://test-data/lb.parquet", "as_of": "2022-06-23",
         "horizon": 21, "n_paths": 0},
        None,
    )
    assert out["status"] == "error"
    assert "n_paths" in out["message"]


def _container_env_for(event):
    """Invoke the launcher with a mocked ECS client and return the env dict it
    would set on the Fargate container (captured from the run_task overrides)."""
    ecs = MagicMock()
    ecs.run_task.return_value = {"tasks": [{"taskArn": "arn:aws:ecs:::task/x"}]}
    with patch.object(handler.boto3, "client", return_value=ecs):
        out = handler.handler(event, None)
    assert out["status"] == "ok", out
    env = ecs.run_task.call_args.kwargs["overrides"]["containerOverrides"][0]["environment"]
    return {e["name"]: e["value"] for e in env}


def test_launcher_forwards_conditioning_as_env(ecs_env):
    env = _container_env_for(
        {"panel_uri": "s3://test-data/lb.parquet", "as_of": "2022-06-23",
         "horizon": 21, "n_paths": 200,
         "conditioning": {"series_shifts": {"USDEUR": -0.1}, "n_anchor_days": 30}},
    )
    assert json.loads(env["CONDITIONING_JSON"]) == {
        "series_shifts": {"USDEUR": -0.1}, "n_anchor_days": 30}


def test_launcher_omits_conditioning_when_absent(ecs_env):
    env = _container_env_for(
        {"panel_uri": "s3://test-data/lb.parquet", "as_of": "2022-06-23",
         "horizon": 21, "n_paths": 200},
    )
    assert "CONDITIONING_JSON" not in env
