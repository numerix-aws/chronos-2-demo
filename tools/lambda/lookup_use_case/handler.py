"""lookup_use_case tool: serve curated adjacent-use-case briefs.

Inputs:  {"topic": str?}            # if absent, returns list of topics
Outputs: {"topic": str, "summary": str, "markdown": str} | {"topics": [str, ...]}
"""
from __future__ import annotations
import json
import os
from pathlib import Path

from tools.lambda_.shared import responses
from tools.lambda_.shared.bedrock import bedrock_action


def _index() -> dict:
    root = Path(os.environ["KNOWLEDGE_DIR"])
    return json.loads((root / "index.json").read_text())


@bedrock_action
def handler(event: dict, _ctx) -> dict:
    idx = _index()
    topic = event.get("topic")
    if not topic:
        return responses.ok({"topics": sorted(idx.keys())})
    if topic not in idx:
        return responses.error(
            f"unknown topic {topic!r}; available: {sorted(idx.keys())}"
        )
    root = Path(os.environ["KNOWLEDGE_DIR"])
    md = (root / idx[topic]["file"]).read_text()
    return responses.ok({
        "topic": topic,
        "summary": idx[topic]["summary"],
        "markdown": md,
    })
