"""Adapter bridging Bedrock action-group invocations to flat-dict handlers.

Bedrock invokes an action-group Lambda with a nested event:

    {"messageVersion": "1.0", "actionGroup": "...", "apiPath": "/load_data",
     "httpMethod": "POST",
     "requestBody": {"content": {"application/json": {"properties": [
         {"name": "as_of_date", "type": "string", "value": "2022-06-30"}, ...]}}}}

and expects a nested response:

    {"messageVersion": "1.0", "response": {"actionGroup": ..., "apiPath": ...,
     "httpMethod": ..., "httpStatusCode": 200,
     "responseBody": {"application/json": {"body": "<json string>"}}}}

Our tool handlers take a FLAT event ({"as_of_date": ...}) and return the
{"status": ...} envelope. `@bedrock_action` wraps such a handler so the same
function works both in unit tests (flat) and behind AgentCore (nested).
"""
from __future__ import annotations

import json
from functools import wraps


def _flatten(event: dict) -> dict:
    """Pull Bedrock requestBody properties + parameters into a flat dict.

    A flat event (no 'messageVersion') is passed through unchanged so handlers
    stay directly unit-testable.
    """
    if "messageVersion" not in event:
        return event
    flat: dict = {}
    for p in event.get("parameters", []) or []:
        flat[p["name"]] = p.get("value")
    content = (event.get("requestBody", {}) or {}).get("content", {}) or {}
    props = (content.get("application/json", {}) or {}).get("properties", []) or []
    for p in props:
        flat[p["name"]] = p.get("value")
    return flat


def bedrock_action(handler):
    @wraps(handler)
    def wrapper(event: dict, ctx):
        if "messageVersion" not in event:
            return handler(event, ctx)  # flat path (unit tests / direct invoke)
        envelope = handler(_flatten(event), ctx)
        status_code = 200 if envelope.get("status") == "ok" else 400
        return {
            "messageVersion": "1.0",
            "response": {
                "actionGroup": event.get("actionGroup"),
                "apiPath": event.get("apiPath"),
                "httpMethod": event.get("httpMethod", "POST"),
                "httpStatusCode": status_code,
                "responseBody": {"application/json": {"body": json.dumps(envelope)}},
            },
        }

    return wrapper
