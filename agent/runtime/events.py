"""Translate verbose Strands stream events into the demo UI protocol."""
from __future__ import annotations

import json
from typing import Any


def _decode_tool_content(content: Any) -> Any:
    if not isinstance(content, list):
        return content
    for item in content:
        if not isinstance(item, dict):
            continue
        if "json" in item:
            return item["json"]
        if "text" in item:
            text = item["text"]
            if not isinstance(text, str):
                return text
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}
    return {"content": content}


def _canonical_tool_name(name: str) -> str:
    return name.rsplit("___", 1)[-1]


class StrandsEventTranslator:
    """Keep only text deltas and deterministic tool lifecycle events."""

    def __init__(self) -> None:
        self._tool_names: dict[str, str] = {}
        self._started: set[str] = set()
        self._completed: set[str] = set()

    def _completion_event(self, result_block: dict[str, Any]) -> dict[str, Any] | None:
        tool_use_id = result_block.get("toolUseId") or result_block.get("tool_use_id")
        if not isinstance(tool_use_id, str) or tool_use_id in self._completed:
            return None

        payload = _decode_tool_content(result_block.get("content", []))
        result_status = str(result_block.get("status", "success")).lower()
        payload_status = payload.get("status") if isinstance(payload, dict) else None
        failed = result_status in {"error", "failed"} or payload_status == "error"
        name = result_block.get("name") or self._tool_names.get(tool_use_id, "unknown_tool")
        self._completed.add(tool_use_id)
        return {
            "type": "tool",
            "tool_use_id": tool_use_id,
            "name": name,
            "status": "failed" if failed else "done",
            "result": payload,
        }

    def translate(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        outgoing: list[dict[str, Any]] = []

        data = event.get("data")
        if isinstance(data, str) and data:
            outgoing.append({"type": "text", "text": data})

        current = event.get("current_tool_use")
        if isinstance(current, dict):
            tool_use_id = current.get("toolUseId")
            name = current.get("name")
            if isinstance(tool_use_id, str) and isinstance(name, str) and name:
                name = _canonical_tool_name(name)
                self._tool_names[tool_use_id] = name
                if tool_use_id not in self._started:
                    self._started.add(tool_use_id)
                    outgoing.append({
                        "type": "tool",
                        "tool_use_id": tool_use_id,
                        "name": name,
                        "status": "running",
                        "input": current.get("input", {}),
                    })

        direct_result = event.get("tool_result")
        if isinstance(direct_result, dict):
            completion = self._completion_event(direct_result)
            if completion:
                outgoing.append(completion)

        message = event.get("message")
        if not isinstance(message, dict):
            return outgoing
        content = message.get("content")
        if not isinstance(content, list):
            return outgoing

        for block in content:
            if not isinstance(block, dict):
                continue
            result_block = block.get("toolResult") or block.get("tool_result")
            if not isinstance(result_block, dict):
                continue
            completion = self._completion_event(result_block)
            if completion:
                outgoing.append(completion)

        return outgoing
