"""Deterministic quantitative execution through the AgentCore MCP Gateway."""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Generator
import uuid

from chronos2_demo.run_spec import canonical_run_payload


def _value(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _canonical_name(name: str) -> str:
    return name.rsplit("___", 1)[-1]


def _available_tools(client) -> dict[str, str]:
    available = {}
    for tool in client.list_tools_sync():
        name = _value(tool, "tool_name")
        if not isinstance(name, str):
            raise RuntimeError("Gateway returned a tool without a tool_name")
        available[_canonical_name(name)] = name
    return available


def _validate_envelope(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RuntimeError("Gateway tool payload was not an object")
    status = payload.get("status")
    if status == "ok" and isinstance(payload.get("result"), dict):
        return payload
    if status == "error" and isinstance(payload.get("message"), str):
        return payload
    raise RuntimeError("Gateway tool payload was not a valid result envelope")


def _decode_content(content: Any) -> dict[str, Any]:
    if not isinstance(content, list) or not content:
        raise RuntimeError("Gateway returned no tool content")
    first = content[0]
    json_value = _value(first, "json")
    if json_value is not None:
        return _validate_envelope(json_value)
    text = _value(first, "text")
    if not isinstance(text, str):
        raise RuntimeError("Gateway tool content was not JSON text")
    try:
        return _validate_envelope(json.loads(text))
    except json.JSONDecodeError as exc:
        raise RuntimeError("Gateway tool content was not valid JSON") from exc


def _decode_call_result(raw: Any) -> dict[str, Any]:
    status = _value(raw, "status")
    structured = _value(raw, "structuredContent")
    if structured is None:
        structured = _value(raw, "structured_content")
    if structured is not None:
        return _validate_envelope(structured)

    content = _value(raw, "content")
    if status in {"error", "failed"}:
        try:
            envelope = _decode_content(content)
        except RuntimeError:
            if isinstance(content, list) and content:
                message = _value(content[0], "text")
                if isinstance(message, str):
                    return {"status": "error", "message": message}
            raise
        if envelope["status"] == "error":
            return envelope
        return {"status": "error", "message": "Gateway reported tool failure"}
    return _decode_content(content)


class WorkflowRunner:
    def __init__(self, client, *, sleep: Callable[[float], None] = time.sleep) -> None:
        self.client = client
        self.sleep = sleep
        self.names = _available_tools(client)

    def call(
        self, name: str, arguments: dict[str, Any]
    ) -> Generator[dict[str, Any], None, dict[str, Any]]:
        tool_use_id = str(uuid.uuid4())
        yield {
            "type": "tool",
            "tool_use_id": tool_use_id,
            "name": name,
            "status": "running",
            "input": arguments,
        }
        try:
            raw = self.client.call_tool_sync(
                tool_use_id=tool_use_id,
                name=self.names[name],
                arguments=arguments,
            )
            envelope = _decode_call_result(raw)
        except Exception as exc:
            yield {
                "type": "tool",
                "tool_use_id": tool_use_id,
                "name": name,
                "status": "failed",
                "result": {"status": "error", "message": str(exc)},
            }
            raise RuntimeError(f"{name} failed: {exc}") from exc
        if envelope["status"] != "ok":
            yield {
                "type": "tool",
                "tool_use_id": tool_use_id,
                "name": name,
                "status": "failed",
                "result": envelope,
            }
            raise RuntimeError(f"{name} failed: {envelope['message']}")
        yield {
            "type": "tool",
            "tool_use_id": tool_use_id,
            "name": name,
            "status": "done",
            "result": envelope,
        }
        result = envelope["result"]
        if name == "price_book":
            yield {
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
            }
        if name == "blend_paths":
            yield {
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
            }
        return result

    def poll(
        self,
        name: str,
        *,
        execution_id: str,
        task_arn: str,
        paths_uri: str,
    ) -> Generator[dict[str, Any], None, dict[str, Any]]:
        while True:
            result = yield from self.call(name, {
                "execution_id": execution_id,
                "task_arn": task_arn,
                "paths_uri": paths_uri,
            })
            if result.get("ready") is True:
                return result
            self.sleep(2.0)


def run_quantitative_workflow(
    client,
    spec,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> Generator[dict[str, Any], None, dict[str, Any]]:
    runner = WorkflowRunner(client, sleep=sleep)
    execution = {"execution_id": spec.execution_id}
    loaded = yield from runner.call(
        "load_data", {**execution, "session_id": spec.execution_id}
    )
    regime_plot = yield from runner.call("plot", {
        **execution,
        "spec": "regime_ribbon",
        "regimes_uri": loaded["regimes_uri"],
    })
    baseline_launch = yield from runner.call("run_baseline_mc", {
        **execution,
        "panel_uri": loaded["panel_uri"],
    })
    baseline = yield from runner.poll(
        "check_baseline_mc",
        execution_id=spec.execution_id,
        task_arn=baseline_launch["task_arn"],
        paths_uri=baseline_launch["paths_uri"],
    )
    chronos_launch = yield from runner.call("run_chronos2", {
        **execution,
        "panel_uri": loaded["panel_uri"],
        "covariates_uri": loaded["covariates_uri"],
    })
    chronos = yield from runner.poll(
        "check_chronos2",
        execution_id=spec.execution_id,
        task_arn=chronos_launch["task_arn"],
        paths_uri=chronos_launch["paths_uri"],
    )
    blend = yield from runner.call("blend_paths", {
        **execution,
        "parametric_uri": baseline["paths_uri"],
        "chronos2_uri": chronos["paths_uri"],
    })
    baseline_metrics = yield from runner.call("price_book", {
        **execution,
        "paths_uri": baseline["paths_uri"],
    })
    chronos_metrics = yield from runner.call("price_book", {
        **execution,
        "paths_uri": chronos["paths_uri"],
    })
    augmented_metrics = yield from runner.call("price_book", {
        **execution,
        "paths_uri": blend["blended_uri"],
    })
    pfe_plot = yield from runner.call("plot", {
        **execution,
        "spec": "pfe_overlay",
        "baseline_uri": baseline_metrics["metrics_uri"],
        "augmented_uri": augmented_metrics["metrics_uri"],
    })
    return {
        "run_spec": canonical_run_payload(spec),
        "exposure": {
            "baseline": baseline_metrics,
            "chronos_only": chronos_metrics,
            "augmented": augmented_metrics,
        },
        "diagnostics": blend["diagnostics"],
        "plots": {
            "regime_ribbon": regime_plot,
            "pfe_overlay": pfe_plot,
        },
    }
