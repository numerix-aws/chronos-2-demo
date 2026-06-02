"""Shared pytest fixtures for Lambda handler tests."""
import os
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

# Map physical `tools/lambda/` dir to importable `tools.lambda_` package.
_REPO = Path(__file__).resolve().parents[2]
_LAMBDA_DIR = _REPO / "tools" / "lambda"
sys.path.insert(0, str(_REPO))

# Make `import tools.lambda_.shared.responses` resolve to tools/lambda/shared/responses.py
import importlib
import types

if "tools" not in sys.modules:
    tools_pkg = types.ModuleType("tools")
    tools_pkg.__path__ = [str(_REPO / "tools")]
    sys.modules["tools"] = tools_pkg

lambda_pkg = types.ModuleType("tools.lambda_")
lambda_pkg.__path__ = [str(_LAMBDA_DIR)]
sys.modules["tools.lambda_"] = lambda_pkg


@pytest.fixture
def aws_creds(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def s3(aws_creds):
    with mock_aws():
        client = boto3.client("s3")
        client.create_bucket(Bucket="test-data")
        client.create_bucket(Bucket="test-plots")
        yield client


@pytest.fixture
def sessions_table(monkeypatch):
    """Mocked DynamoDB sessions table; returns the table name."""
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName="sessions",
            KeySchema=[
                {"AttributeName": "session_id", "KeyType": "HASH"},
                {"AttributeName": "turn_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "session_id", "AttributeType": "S"},
                {"AttributeName": "turn_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield "sessions"
