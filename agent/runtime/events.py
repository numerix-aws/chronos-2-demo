"""Translate verbose Strands stream events into the demo UI protocol."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
import math
import re
from typing import Any
from urllib.parse import urlparse


SOURCE_ROLES = {
    "parametric": "baseline",
    "chronos2": "chronos_only",
    "chronos2_conditional": "chronos_only",
    "blended": "augmented",
}

PRICE_FIELDS = {
    "execution_id", "spec_hash", "scenario_role", "source", "paths_uri",
    "paths_sha256", "ee", "pfe_975", "es_975", "dates", "terminal",
    "metrics_uri", "metrics_sha256",
}
BLEND_FIELDS = {
    "execution_id", "spec_hash", "blended_uri", "blended_sha256",
    "diagnostics_uri", "diagnostics_sha256", "diagnostics", "w_stress",
    "n_paths",
}


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


def _require_fields(result: dict[str, Any], required: set[str]) -> None:
    missing = sorted(required - result.keys())
    if missing:
        raise ValueError(f"missing required fields: {missing}")


def _require_string(result: dict[str, Any], field: str) -> str:
    value = result[field]
    if not isinstance(value, str) or not value:
        raise ValueError(f"field {field} must be a nonempty string")
    return value


def _require_sha256(result: dict[str, Any], field: str) -> None:
    value = _require_string(result, field)
    if len(value) != 64 or any(char not in "0123456789abcdefABCDEF" for char in value):
        raise ValueError(f"field {field} must be a SHA-256 hex digest")


def _require_run_uri(result: dict[str, Any], field: str, execution_id: str) -> str:
    value = _require_string(result, field)
    parsed = urlparse(value)
    if (
        parsed.scheme != "s3"
        or not parsed.netloc
        or not parsed.path.lstrip("/").startswith(f"runs/{execution_id}/")
    ):
        raise ValueError(f"field {field} must belong to execution {execution_id}")
    return value


def _require_number(value: Any, field: str) -> None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise ValueError(f"field {field} must be a finite number")


def _result_body(envelope: Any) -> dict[str, Any]:
    if (
        not isinstance(envelope, dict)
        or envelope.get("status") != "ok"
        or not isinstance(envelope.get("result"), dict)
    ):
        raise ValueError("successful result must contain an ok result envelope")
    try:
        json.dumps(envelope, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("result must contain strict finite JSON") from exc
    return envelope["result"]


def _validate_identity(
    result: dict[str, Any],
    tool_input: dict[str, Any],
) -> tuple[str, str]:
    execution_id = _require_string(result, "execution_id")
    spec_hash = _require_string(result, "spec_hash")
    if tool_input.get("execution_id") != execution_id:
        raise ValueError("execution_id does not match tool input")
    _require_sha256(result, "spec_hash")
    return execution_id, spec_hash


def _validate_price_result(envelope: Any, tool_input: dict[str, Any]) -> None:
    result = _result_body(envelope)
    _require_fields(result, PRICE_FIELDS)
    execution_id, _ = _validate_identity(result, tool_input)

    source = _require_string(result, "source")
    role = _require_string(result, "scenario_role")
    if SOURCE_ROLES.get(source) != role:
        raise ValueError("scenario_role does not match source")

    paths_uri = _require_run_uri(result, "paths_uri", execution_id)
    if tool_input.get("paths_uri") != paths_uri:
        raise ValueError("paths_uri does not match tool input")
    expected_filename = {
        "parametric": "baseline.pkl",
        "chronos2": "chronos2.pkl",
        "chronos2_conditional": "chronos2.pkl",
        "blended": "blended.pkl",
    }[source]
    if urlparse(paths_uri).path.lstrip("/") != f"runs/{execution_id}/{expected_filename}":
        raise ValueError("paths_uri does not match source")
    _require_sha256(result, "paths_sha256")
    metrics_uri = _require_run_uri(result, "metrics_uri", execution_id)
    if urlparse(metrics_uri).path.lstrip("/") != (
        f"runs/{execution_id}/metrics/{role}.json"
    ):
        raise ValueError("metrics_uri does not match scenario_role")
    _require_sha256(result, "metrics_sha256")

    dates = result["dates"]
    metrics = [result[field] for field in ("ee", "pfe_975", "es_975")]
    if (
        not isinstance(dates, list)
        or not dates
        or not all(isinstance(value, str) and value for value in dates)
        or not all(isinstance(values, list) for values in metrics)
        or any(len(values) != len(dates) for values in metrics)
    ):
        raise ValueError("exposure metric arrays must align with nonempty dates")
    for field, values in zip(("ee", "pfe_975", "es_975"), metrics):
        for value in values:
            _require_number(value, field)

    terminal = result["terminal"]
    if not isinstance(terminal, dict):
        raise ValueError("field terminal must be an object")
    terminal_fields = {"date", "ee", "pfe_975", "es_975"}
    if set(terminal) != terminal_fields:
        raise ValueError("field terminal must contain exactly date, ee, pfe_975, es_975")
    terminal_date = terminal["date"]
    if not isinstance(terminal_date, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}",
        terminal_date,
    ):
        raise ValueError("terminal date must be a canonical ISO calendar date")
    try:
        parsed_terminal_date = date.fromisoformat(terminal_date)
    except ValueError as exc:
        raise ValueError("terminal date must be a canonical ISO calendar date") from exc
    if parsed_terminal_date.isoformat() != terminal_date:
        raise ValueError("terminal date must be a canonical ISO calendar date")
    if terminal_date != dates[-1]:
        raise ValueError("terminal date does not match the final metric date")
    for field, values in zip(("ee", "pfe_975", "es_975"), metrics):
        _require_number(terminal[field], f"terminal.{field}")
        if terminal[field] != values[-1]:
            raise ValueError(f"terminal {field} does not match final metric value")


def _validate_blend_result(envelope: Any, tool_input: dict[str, Any]) -> None:
    result = _result_body(envelope)
    _require_fields(result, BLEND_FIELDS)
    execution_id, spec_hash = _validate_identity(result, tool_input)
    blended_uri = _require_run_uri(result, "blended_uri", execution_id)
    if urlparse(blended_uri).path.lstrip("/") != f"runs/{execution_id}/blended.pkl":
        raise ValueError("blended_uri does not match the canonical artifact")
    _require_sha256(result, "blended_sha256")
    diagnostics_uri = _require_run_uri(result, "diagnostics_uri", execution_id)
    if urlparse(diagnostics_uri).path.lstrip("/") != (
        f"runs/{execution_id}/diagnostics.json"
    ):
        raise ValueError("diagnostics_uri does not match the canonical artifact")
    _require_sha256(result, "diagnostics_sha256")

    diagnostics = result["diagnostics"]
    if not isinstance(diagnostics, dict):
        raise ValueError("field diagnostics must be an object")
    if diagnostics.get("execution_id") != execution_id:
        raise ValueError("diagnostics execution_id mismatch")
    if diagnostics.get("spec_hash") != spec_hash:
        raise ValueError("diagnostics spec_hash mismatch")
    _require_number(result["w_stress"], "w_stress")
    if (
        not isinstance(result["n_paths"], int)
        or isinstance(result["n_paths"], bool)
        or result["n_paths"] <= 0
    ):
        raise ValueError("field n_paths must be a positive integer")


def _structured_events(completion: dict[str, Any]) -> list[dict[str, Any]]:
    if completion.get("status") != "done":
        return []
    result = completion["result"]["result"]
    if completion.get("name") == "price_book":
        return [{
            "type": "exposure_result",
            **{
                key: result[key]
                for key in (
                    "execution_id",
                    "spec_hash",
                    "scenario_role",
                    "source",
                    "paths_uri",
                    "paths_sha256",
                    "metrics_uri",
                    "metrics_sha256",
                    "terminal",
                )
            },
        }]
    if completion.get("name") == "blend_paths":
        return [{
            "type": "diagnostics",
            **{
                key: result[key]
                for key in (
                    "execution_id",
                    "spec_hash",
                    "diagnostics_uri",
                    "diagnostics_sha256",
                    "diagnostics",
                )
            },
        }]
    return []


class StrandsEventTranslator:
    """Keep only text deltas and deterministic tool lifecycle events."""

    def __init__(self) -> None:
        self._tool_names: dict[str, str] = {}
        self._tool_inputs: dict[str, dict[str, Any]] = {}
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
        name = self._tool_names.get(tool_use_id) or result_block.get("name") or "unknown_tool"
        if isinstance(name, str):
            name = _canonical_tool_name(name)
        if not failed and name in {"price_book", "blend_paths"}:
            try:
                validator = (
                    _validate_price_result
                    if name == "price_book"
                    else _validate_blend_result
                )
                validator(payload, self._tool_inputs.get(tool_use_id, {}))
            except ValueError as exc:
                failed = True
                payload = {
                    "status": "error",
                    "message": f"{name} result validation failed: {exc}",
                }
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
            tool_input = current.get("input")
            canonical_name = (
                _canonical_tool_name(name)
                if isinstance(name, str)
                else None
            )
            if (
                isinstance(tool_use_id, str)
                and canonical_name
                and isinstance(tool_input, dict)
                and tool_use_id not in self._started
            ):
                bound_input = deepcopy(tool_input)
                self._tool_names[tool_use_id] = canonical_name
                self._tool_inputs[tool_use_id] = bound_input
                self._started.add(tool_use_id)
                outgoing.append({
                    "type": "tool",
                    "tool_use_id": tool_use_id,
                    "name": canonical_name,
                    "status": "running",
                    "input": deepcopy(bound_input),
                })

        direct_result = event.get("tool_result")
        if isinstance(direct_result, dict):
            completion = self._completion_event(direct_result)
            if completion:
                outgoing.append(completion)
                outgoing.extend(_structured_events(completion))

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
                outgoing.extend(_structured_events(completion))

        return outgoing
