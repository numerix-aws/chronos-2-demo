"""Tests for the sessions REST Lambda."""
import json
import os

import pytest

from tools.lambda_.sessions import handler


def _event(method: str, path: str, body=None, path_params=None) -> dict:
    return {
        "httpMethod": method,
        "resource": path,
        "pathParameters": path_params or {},
        "body": json.dumps(body) if body is not None else None,
    }


def test_post_sessions_creates_session(sessions_table, monkeypatch):
    monkeypatch.setenv("SESSIONS_TABLE", sessions_table)
    resp = handler.handler(_event("POST", "/sessions"), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "session_id" in body
    assert len(body["session_id"]) == 36  # uuid4


def test_post_messages_appends_turn(sessions_table, monkeypatch):
    monkeypatch.setenv("SESSIONS_TABLE", sessions_table)
    sid = json.loads(handler.handler(_event("POST", "/sessions"), None)["body"])["session_id"]

    resp = handler.handler(
        _event(
            "POST",
            "/sessions/{sid}/messages",
            body={"role": "user", "content": "run baseline"},
            path_params={"sid": sid},
        ),
        None,
    )
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["turn_id"]


def test_get_messages_returns_history_in_order(sessions_table, monkeypatch):
    monkeypatch.setenv("SESSIONS_TABLE", sessions_table)
    sid = json.loads(handler.handler(_event("POST", "/sessions"), None)["body"])["session_id"]
    for i in range(3):
        handler.handler(
            _event(
                "POST",
                "/sessions/{sid}/messages",
                body={"role": "user", "content": f"msg {i}"},
                path_params={"sid": sid},
            ),
            None,
        )
    resp = handler.handler(
        _event("GET", "/sessions/{sid}/messages", path_params={"sid": sid}),
        None,
    )
    body = json.loads(resp["body"])
    assert [m["content"] for m in body["messages"]] == ["msg 0", "msg 1", "msg 2"]


def test_post_messages_rejects_invalid_role(sessions_table, monkeypatch):
    monkeypatch.setenv("SESSIONS_TABLE", sessions_table)
    sid = json.loads(handler.handler(_event("POST", "/sessions"), None)["body"])["session_id"]
    resp = handler.handler(
        _event(
            "POST",
            "/sessions/{sid}/messages",
            body={"role": "system", "content": "..."},
            path_params={"sid": sid},
        ),
        None,
    )
    assert resp["statusCode"] == 400


def test_unknown_route_returns_404(sessions_table, monkeypatch):
    monkeypatch.setenv("SESSIONS_TABLE", sessions_table)
    resp = handler.handler(_event("GET", "/nope"), None)
    assert resp["statusCode"] == 404
