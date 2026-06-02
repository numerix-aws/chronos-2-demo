"""Lambda Function URL SSE relay.

AgentCore Runtime returns a streaming response from `invoke_agent_runtime`. We
re-emit each chunk as a Server-Sent Event ("data: <text>\\n\\n"). The actual
deployable is the Node 20 streaming entrypoint (`index.mjs`); this Python module
exists for unit-testing the parsing helpers and the auth check, and the Node
shim mirrors the same logic.
"""
from __future__ import annotations

import os
from typing import Iterable, Iterator

import boto3

_SECRETS = None


def _secrets():
    global _SECRETS
    if _SECRETS is None:
        _SECRETS = boto3.client("secretsmanager")
    return _SECRETS


def _authorize(headers: dict[str, str]) -> bool:
    expected = _secrets().get_secret_value(SecretId=os.environ["API_KEY_SECRET_ARN"])[
        "SecretString"
    ]
    for k, v in headers.items():
        if k.lower() == "x-api-key":
            return v == expected
    return False


def _sse(text: str) -> str:
    """Format `text` as an SSE event (multi-line safe)."""
    lines = text.split("\n")
    return "".join(f"data: {line}\n" for line in lines) + "\n"


def _iter_chunks(raw: dict) -> Iterator[str]:
    # invoke_agent_runtime returns {"response": <iterable of byte chunks>}.
    for chunk in raw["response"]:
        yield (chunk if isinstance(chunk, bytes) else str(chunk).encode("utf-8")).decode(
            "utf-8", errors="replace"
        )


def stream_sse(session_id: str, prompt: str) -> Iterable[str]:
    """Generator suitable for a streaming HTTP body."""
    import json

    rt = boto3.client("bedrock-agentcore")
    raw = rt.invoke_agent_runtime(
        agentRuntimeArn=os.environ["AGENT_RUNTIME_ARN"],
        runtimeSessionId=session_id,
        payload=json.dumps({"prompt": prompt}).encode("utf-8"),
    )
    for chunk in _iter_chunks(raw):
        yield _sse(chunk)
    yield _sse("[DONE]")
