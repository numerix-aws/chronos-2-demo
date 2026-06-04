import boto3
import json
import pytest
from moto import mock_aws

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
