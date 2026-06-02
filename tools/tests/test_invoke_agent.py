"""Tests for the synchronous agent-invocation Lambda."""
import json
from unittest.mock import patch

import pytest

from tools.lambda_.invoke_agent import handler


def _event(body: dict) -> dict:
    return {"httpMethod": "POST", "resource": "/invoke", "body": json.dumps(body)}


@pytest.fixture
def env(sessions_table, monkeypatch):
    monkeypatch.setenv("SESSIONS_TABLE", sessions_table)
    monkeypatch.setenv("AGENT_RUNTIME_ARN", "arn:aws:bedrock-agentcore:us-east-1:000:runtime/x/endpoint/live")


def _fake_agent_response(text: str) -> dict:
    """Shape mirrors bedrock-agentcore invoke_agent_runtime response."""
    return {"contentType": "application/json", "response": iter([text.encode("utf-8")])}


def test_invoke_persists_turns_and_returns_text(env):
    body = {"session_id": "s1", "prompt": "run baseline"}
    with patch.object(
        handler, "_invoke_agent", return_value=_fake_agent_response("ok, running")
    ) as mocked:
        resp = handler.handler(_event(body), None)

    assert resp["statusCode"] == 200
    out = json.loads(resp["body"])
    assert out["text"] == "ok, running"
    mocked.assert_called_once()


def test_invoke_concatenates_multiple_chunks(env):
    body = {"session_id": "s1", "prompt": "x"}
    with patch.object(
        handler,
        "_invoke_agent",
        return_value={"contentType": "application/json", "response": iter([b"hello ", b"world"])},
    ):
        resp = handler.handler(_event(body), None)
    assert json.loads(resp["body"])["text"] == "hello world"


def test_invoke_validates_payload(env):
    resp = handler.handler(_event({"prompt": "x"}), None)
    assert resp["statusCode"] == 400
    resp = handler.handler(_event({"session_id": "s1"}), None)
    assert resp["statusCode"] == 400
