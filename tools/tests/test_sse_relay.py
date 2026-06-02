"""Unit tests for SSE relay Lambda — runs in-process, no streaming runtime."""
import json
from unittest.mock import patch, MagicMock

import pytest

from tools.lambda_.sse_relay import handler


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("AGENT_RUNTIME_ARN", "arn:aws:bedrock-agentcore:us-east-1:000:runtime/x/endpoint/live")
    monkeypatch.setenv("API_KEY_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:000:secret:k")


def test_format_sse_event_emits_data_line():
    line = handler._sse("hello")
    assert line == "data: hello\n\n"


def test_format_sse_event_handles_multiline():
    line = handler._sse("line1\nline2")
    assert line == "data: line1\ndata: line2\n\n"


def test_iter_chunks_yields_decoded_text(env):
    # invoke_agent_runtime returns {"response": <iterable of byte chunks>}.
    raw = {"contentType": "application/json", "response": iter([b"hello ", b"world"])}
    out = list(handler._iter_chunks(raw))
    assert out == ["hello ", "world"]


def test_authorize_rejects_wrong_key(env, monkeypatch):
    secret = MagicMock()
    secret.get_secret_value.return_value = {"SecretString": "right-key"}
    monkeypatch.setattr(handler, "_secrets", lambda: secret)
    assert handler._authorize({"x-api-key": "wrong"}) is False
    assert handler._authorize({"x-api-key": "right-key"}) is True


def test_authorize_is_case_insensitive(env, monkeypatch):
    secret = MagicMock()
    secret.get_secret_value.return_value = {"SecretString": "k"}
    monkeypatch.setattr(handler, "_secrets", lambda: secret)
    assert handler._authorize({"X-Api-Key": "k"}) is True
