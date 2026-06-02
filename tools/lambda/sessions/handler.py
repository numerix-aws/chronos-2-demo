"""REST sessions handler: create sessions and append/list transcript turns."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from tools.lambda_.shared import responses

VALID_ROLES = {"user", "assistant", "tool"}


def _table():
    return boto3.resource("dynamodb").Table(os.environ["SESSIONS_TABLE"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _create_session() -> dict[str, Any]:
    sid = str(uuid.uuid4())
    _table().put_item(
        Item={
            "session_id": sid,
            "turn_id": "0000-meta",
            "role": "meta",
            "content": "session created",
            "created_at": _now_iso(),
        }
    )
    return responses.http_ok({"session_id": sid})


def _append_message(sid: str, body: dict) -> dict[str, Any]:
    role = body.get("role")
    content = body.get("content")
    if role not in VALID_ROLES:
        return responses.http_error(f"invalid role: {role!r}", status=400)
    if not isinstance(content, str) or not content:
        return responses.http_error("content must be a non-empty string", status=400)

    turn_id = f"{_now_iso()}#{role}"
    item = {
        "session_id": sid,
        "turn_id": turn_id,
        "role": role,
        "content": content,
    }
    if "tool_name" in body:
        item["tool_name"] = str(body["tool_name"])
    if "trace_id" in body:
        item["trace_id"] = str(body["trace_id"])

    _table().put_item(Item=item)
    return responses.http_ok({"turn_id": turn_id})


def _list_messages(sid: str) -> dict[str, Any]:
    resp = _table().query(
        KeyConditionExpression=Key("session_id").eq(sid),
        ScanIndexForward=True,
    )
    messages = [
        {k: v for k, v in item.items() if k != "session_id"}
        for item in resp.get("Items", [])
        if item.get("role") in VALID_ROLES
    ]
    return responses.http_ok({"messages": messages})


def handler(event: dict, _context) -> dict[str, Any]:
    method = event.get("httpMethod")
    resource = event.get("resource", "")
    body = json.loads(event["body"]) if event.get("body") else {}
    sid = (event.get("pathParameters") or {}).get("sid")

    if method == "POST" and resource == "/sessions":
        return _create_session()
    if method == "POST" and resource == "/sessions/{sid}/messages" and sid:
        return _append_message(sid, body)
    if method == "GET" and resource == "/sessions/{sid}/messages" and sid:
        return _list_messages(sid)

    return responses.http_error(f"no route for {method} {resource}", status=404)
