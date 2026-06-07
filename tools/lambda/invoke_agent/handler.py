"""Synchronous agent invocation: POST /invoke {session_id, prompt} → {text}."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import boto3

from tools.lambda_.shared import responses

_AGENT_RUNTIME = None


def _agent_runtime():
    global _AGENT_RUNTIME
    if _AGENT_RUNTIME is None:
        _AGENT_RUNTIME = boto3.client("bedrock-agentcore")
    return _AGENT_RUNTIME


def _invoke_agent(session_id: str, prompt: str) -> dict:
    """Thin wrapper so tests can patch a single seam."""
    # AGENT_RUNTIME_ARN is the runtime ARN; the named endpoint ("live") is passed
    # separately as the qualifier. Passing the endpoint ARN as agentRuntimeArn
    # makes boto3 default qualifier to 'DEFAULT' -> ResourceNotFoundException.
    return _agent_runtime().invoke_agent_runtime(
        agentRuntimeArn=os.environ["AGENT_RUNTIME_ARN"],
        qualifier=os.environ.get("AGENT_QUALIFIER", "live"),
        runtimeSessionId=session_id,
        payload=json.dumps({"prompt": prompt}).encode("utf-8"),
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _persist(sid: str, role: str, content: str) -> None:
    boto3.resource("dynamodb").Table(os.environ["SESSIONS_TABLE"]).put_item(
        Item={
            "session_id": sid,
            "turn_id": f"{_now_iso()}#{role}",
            "role": role,
            "content": content,
        }
    )


def handler(event: dict, _context) -> dict[str, Any]:
    body = json.loads(event["body"]) if event.get("body") else {}
    sid = body.get("session_id")
    prompt = body.get("prompt")
    if not sid or not prompt:
        return responses.http_error("session_id and prompt required", status=400)

    _persist(sid, "user", prompt)

    raw = _invoke_agent(sid, prompt)
    parts: list[bytes] = []
    for chunk in raw["response"]:
        parts.append(chunk if isinstance(chunk, bytes) else str(chunk).encode("utf-8"))
    text = b"".join(parts).decode("utf-8", errors="replace")

    _persist(sid, "assistant", text)
    return responses.http_ok({"text": text})
