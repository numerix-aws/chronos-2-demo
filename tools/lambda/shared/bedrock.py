"""Adapter for AgentCore Gateway → flat-dict tool handlers.

AgentCore Gateway invokes a Lambda target with the tool's input arguments as a
**flat** event dict, e.g. ``{"as_of_date": "2022-06-30", "lookback_days": 60}``,
and expects any valid JSON object back. (The invoked tool's name arrives out of
band on ``context.client_context.custom['bedrockAgentCoreToolName']`` — we don't
need it, since each tool is its own Lambda.)

Our tool handlers already take that flat event and return a JSON-serializable
dict, so the Gateway contract needs no translation. ``@bedrock_action`` is kept
as a thin pass-through so the handler import sites stay stable and we have one
seam to evolve if the Gateway contract ever changes.
"""
from __future__ import annotations

from functools import wraps


def bedrock_action(handler):
    @wraps(handler)
    def wrapper(event: dict, ctx):
        return handler(event, ctx)

    return wrapper
