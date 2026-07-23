"""Deterministic quantitative execution through the AgentCore MCP Gateway."""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Generator
from urllib.parse import urlparse
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


REQUIRED_RESULT_FIELDS = {
    "load_data": (
        "execution_id", "spec_hash", "panel_uri", "panel_sha256",
        "covariates_uri", "covariates_sha256", "regimes_uri",
        "regimes_sha256", "n_rows", "as_of_date",
    ),
    "plot": (
        "execution_id", "spec_hash", "plot_role", "image_s3_uri",
        "image_uri", "image_sha256",
    ),
    "run_baseline_mc": (
        "execution_id", "spec_hash", "task_arn", "paths_uri",
    ),
    "check_baseline_mc": (
        "execution_id", "spec_hash", "task_status", "ready", "paths_uri",
    ),
    "run_chronos2": (
        "execution_id", "spec_hash", "task_arn", "paths_uri",
    ),
    "check_chronos2": (
        "execution_id", "spec_hash", "task_status", "ready", "paths_uri",
    ),
    "blend_paths": (
        "execution_id", "spec_hash", "blended_uri", "blended_sha256",
        "diagnostics_uri", "diagnostics_sha256", "diagnostics",
        "w_stress", "n_paths",
    ),
    "price_book": (
        "execution_id", "spec_hash", "scenario_role", "source", "paths_uri",
        "paths_sha256", "ee", "pfe_975", "es_975", "dates", "terminal",
        "metrics_uri", "metrics_sha256",
    ),
}
READY_PATH_FIELDS = (
    "artifact_uri", "artifact_sha256", "artifact_kind", "source",
    "scenario_role", "producer_version",
)
RUN_OWNED_URI_FIELDS = {
    "load_data": ("panel_uri", "covariates_uri", "regimes_uri"),
    "plot": ("image_s3_uri",),
    "run_baseline_mc": ("paths_uri",),
    "check_baseline_mc": ("paths_uri",),
    "run_chronos2": ("paths_uri",),
    "check_chronos2": ("paths_uri",),
    "blend_paths": ("blended_uri", "diagnostics_uri"),
    "price_book": ("paths_uri", "metrics_uri"),
}


def _require_fields(result: dict[str, Any], fields: tuple[str, ...]) -> None:
    for field in fields:
        if field not in result:
            raise RuntimeError(f"missing required field {field}")


def _require_string(result: dict[str, Any], field: str) -> None:
    if not isinstance(result[field], str) or not result[field]:
        raise RuntimeError(f"field {field} must be a nonempty string")


def _validate_finite_json(result: dict[str, Any]) -> None:
    try:
        json.dumps(result, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("result must be strict finite JSON") from exc


class WorkflowRunner:
    def __init__(
        self,
        client,
        *,
        execution_id: str,
        spec_hash: str,
        max_poll_attempts: int,
        poll_interval_seconds: float,
        poll_budget_seconds: float,
        gateway_call_timeout_seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_poll_attempts < 1:
            raise ValueError("max_poll_attempts must be positive")
        if poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds must be nonnegative")
        if poll_budget_seconds <= 0:
            raise ValueError("poll_budget_seconds must be positive")
        if gateway_call_timeout_seconds <= 0:
            raise ValueError("gateway_call_timeout_seconds must be positive")
        self.client = client
        self.execution_id = execution_id
        self.spec_hash = spec_hash
        self.max_poll_attempts = max_poll_attempts
        self.poll_interval_seconds = poll_interval_seconds
        self.poll_budget_seconds = poll_budget_seconds
        self.gateway_call_timeout_seconds = gateway_call_timeout_seconds
        self.monotonic = monotonic
        self.sleep = sleep
        self.poll_started_at = monotonic()
        self.names = _available_tools(client)

    def _poll_elapsed(self) -> float:
        return max(0.0, self.monotonic() - self.poll_started_at)

    def _poll_remaining(self) -> float:
        return self.poll_budget_seconds - self._poll_elapsed()

    def _poll_error(
        self,
        reason: str,
        *,
        attempt: int,
        latest_status: str,
        task_arn: str,
        tool_name: str,
    ) -> RuntimeError:
        return RuntimeError(
            f"{reason}; attempts={attempt}; elapsed={self._poll_elapsed():.3f}s; "
            f"budget={self.poll_budget_seconds:.3f}s; "
            f"latest task_status={latest_status}; task_arn={task_arn}; "
            f"poll_tool={tool_name}; "
            f"max_call_overrun={self.gateway_call_timeout_seconds:.3f}s"
        )

    def _validate_result(
        self,
        name: str,
        result: dict[str, Any],
        *,
        expected_source: str | None,
        expected_role: str | None,
        expected_plot_role: str | None,
    ) -> None:
        _validate_finite_json(result)
        _require_fields(result, REQUIRED_RESULT_FIELDS[name])
        if result["execution_id"] != self.execution_id:
            raise RuntimeError("execution_id mismatch")
        if result["spec_hash"] != self.spec_hash:
            raise RuntimeError("spec_hash mismatch")
        _require_string(result, "execution_id")
        _require_string(result, "spec_hash")

        string_fields = {
            "load_data": (
                "panel_uri", "panel_sha256", "covariates_uri",
                "covariates_sha256", "regimes_uri", "regimes_sha256",
                "as_of_date",
            ),
            "plot": ("plot_role", "image_s3_uri", "image_uri", "image_sha256"),
            "run_baseline_mc": ("task_arn", "paths_uri"),
            "check_baseline_mc": ("task_status", "paths_uri"),
            "run_chronos2": ("task_arn", "paths_uri"),
            "check_chronos2": ("task_status", "paths_uri"),
            "blend_paths": (
                "blended_uri", "blended_sha256", "diagnostics_uri",
                "diagnostics_sha256",
            ),
            "price_book": (
                "scenario_role", "source", "paths_uri", "paths_sha256",
                "metrics_uri", "metrics_sha256",
            ),
        }[name]
        for field in string_fields:
            _require_string(result, field)
        expected_prefix = f"runs/{self.execution_id}/"
        for field in RUN_OWNED_URI_FIELDS[name]:
            parsed = urlparse(result[field])
            if (
                parsed.scheme != "s3"
                or not parsed.path.lstrip("/").startswith(expected_prefix)
            ):
                raise RuntimeError(f"field {field} has run ownership mismatch")

        if name == "load_data":
            if (
                not isinstance(result["n_rows"], int)
                or isinstance(result["n_rows"], bool)
            ):
                raise RuntimeError("field n_rows must be an integer")
        elif name in {"check_baseline_mc", "check_chronos2"}:
            if not isinstance(result["ready"], bool):
                raise RuntimeError("field ready must be a boolean")
            if result["ready"]:
                _require_fields(result, READY_PATH_FIELDS)
                for field in READY_PATH_FIELDS:
                    _require_string(result, field)
                if result["artifact_uri"] != result["paths_uri"]:
                    raise RuntimeError("artifact_uri does not match paths_uri")
        elif name == "blend_paths":
            if not isinstance(result["diagnostics"], dict):
                raise RuntimeError("field diagnostics must be an object")
            if result["diagnostics"].get("execution_id") != self.execution_id:
                raise RuntimeError("diagnostics execution_id mismatch")
            if result["diagnostics"].get("spec_hash") != self.spec_hash:
                raise RuntimeError("diagnostics spec_hash mismatch")
            if (
                not isinstance(result["n_paths"], int)
                or isinstance(result["n_paths"], bool)
            ):
                raise RuntimeError("field n_paths must be an integer")
        elif name == "price_book":
            for field in ("ee", "pfe_975", "es_975"):
                if not isinstance(result[field], list):
                    raise RuntimeError(f"field {field} must be an array")
                if not all(
                    isinstance(value, (int, float)) and not isinstance(value, bool)
                    for value in result[field]
                ):
                    raise RuntimeError(f"field {field} must contain numbers")
            if not isinstance(result["dates"], list) or not all(
                isinstance(value, str) for value in result["dates"]
            ):
                raise RuntimeError("field dates must contain strings")
            if not isinstance(result["terminal"], dict):
                raise RuntimeError("field terminal must be an object")
            _require_fields(
                result["terminal"],
                ("date", "ee", "pfe_975", "es_975"),
            )
            if not isinstance(result["terminal"]["date"], str):
                raise RuntimeError("terminal date must be a string")
            if not all(
                isinstance(result["terminal"][field], (int, float))
                and not isinstance(result["terminal"][field], bool)
                for field in ("ee", "pfe_975", "es_975")
            ):
                raise RuntimeError("terminal exposure values must be numbers")

        compare_path_role = (
            name not in {"check_baseline_mc", "check_chronos2"}
            or result["ready"] is True
        )
        if (
            expected_source is not None
            and compare_path_role
            and result.get("source") != expected_source
        ):
            raise RuntimeError(
                f"source mismatch: expected {expected_source}, got {result.get('source')}"
            )
        if (
            expected_role is not None
            and compare_path_role
            and result.get("scenario_role") != expected_role
        ):
            raise RuntimeError(
                "scenario_role mismatch: "
                f"expected {expected_role}, got {result.get('scenario_role')}"
            )
        if (
            expected_plot_role is not None
            and result.get("plot_role") != expected_plot_role
        ):
            raise RuntimeError(
                "plot_role mismatch: "
                f"expected {expected_plot_role}, got {result.get('plot_role')}"
            )

    def call(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        expected_source: str | None = None,
        expected_role: str | None = None,
        expected_plot_role: str | None = None,
        before_call: Callable[[], None] | None = None,
        semantic_check: Callable[[dict[str, Any]], None] | None = None,
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
            if before_call is not None:
                before_call()
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
        result = envelope["result"]
        try:
            self._validate_result(
                name,
                result,
                expected_source=expected_source,
                expected_role=expected_role,
                expected_plot_role=expected_plot_role,
            )
            if semantic_check is not None:
                semantic_check(result)
        except Exception as exc:
            failure = {"status": "error", "message": str(exc)}
            yield {
                "type": "tool",
                "tool_use_id": tool_use_id,
                "name": name,
                "status": "failed",
                "result": failure,
            }
            raise RuntimeError(f"{name} failed: {exc}") from exc
        yield {
            "type": "tool",
            "tool_use_id": tool_use_id,
            "name": name,
            "status": "done",
            "result": envelope,
        }
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
        expected_source: str,
        expected_role: str,
    ) -> Generator[dict[str, Any], None, dict[str, Any]]:
        latest_status = "unknown"
        for attempt in range(1, self.max_poll_attempts + 1):
            final_attempt = attempt == self.max_poll_attempts

            def require_budget_before_call() -> None:
                if self._poll_remaining() <= 0:
                    raise self._poll_error(
                        "elapsed polling deadline exhausted before poll call",
                        attempt=attempt,
                        latest_status=latest_status,
                        task_arn=task_arn,
                        tool_name=name,
                    )

            def require_ready(result: dict[str, Any]) -> None:
                nonlocal latest_status
                latest_status = result["task_status"]
                if self._poll_remaining() <= 0:
                    raise self._poll_error(
                        "elapsed polling deadline exceeded during poll call",
                        attempt=attempt,
                        latest_status=latest_status,
                        task_arn=task_arn,
                        tool_name=name,
                    )
                if final_attempt and result["ready"] is not True:
                    raise self._poll_error(
                        "poll attempt limit exhausted",
                        attempt=attempt,
                        latest_status=latest_status,
                        task_arn=task_arn,
                        tool_name=name,
                    )

            result = yield from self.call(
                name,
                {
                    "execution_id": execution_id,
                    "task_arn": task_arn,
                    "paths_uri": paths_uri,
                },
                expected_source=expected_source,
                expected_role=expected_role,
                before_call=require_budget_before_call,
                semantic_check=require_ready,
            )
            if result.get("ready") is True:
                return result
            remaining = self._poll_remaining()
            if remaining <= 0:
                continue
            self.sleep(min(self.poll_interval_seconds, remaining))


def run_quantitative_workflow(
    client,
    spec,
    *,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    max_poll_attempts: int = 300,
    poll_interval_seconds: float = 2.0,
    poll_budget_seconds: float = 600.0,
    gateway_call_timeout_seconds: float = 90.0,
) -> Generator[dict[str, Any], None, dict[str, Any]]:
    runner = WorkflowRunner(
        client,
        execution_id=spec.execution_id,
        spec_hash=spec.spec_hash,
        max_poll_attempts=max_poll_attempts,
        poll_interval_seconds=poll_interval_seconds,
        poll_budget_seconds=poll_budget_seconds,
        gateway_call_timeout_seconds=gateway_call_timeout_seconds,
        monotonic=monotonic,
        sleep=sleep,
    )
    execution = {"execution_id": spec.execution_id}
    loaded = yield from runner.call(
        "load_data", {**execution, "session_id": spec.execution_id}
    )
    regime_plot = yield from runner.call("plot", {
        **execution,
        "spec": "regime_ribbon",
        "regimes_uri": loaded["regimes_uri"],
    }, expected_plot_role="regime_ribbon")
    baseline_launch = yield from runner.call("run_baseline_mc", {
        **execution,
        "panel_uri": loaded["panel_uri"],
    })
    baseline = yield from runner.poll(
        "check_baseline_mc",
        execution_id=spec.execution_id,
        task_arn=baseline_launch["task_arn"],
        paths_uri=baseline_launch["paths_uri"],
        expected_source="parametric",
        expected_role="baseline",
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
        expected_source=(
            "chronos2_conditional" if spec.conditioning else "chronos2"
        ),
        expected_role="chronos_only",
    )
    blend = yield from runner.call("blend_paths", {
        **execution,
        "parametric_uri": baseline["paths_uri"],
        "chronos2_uri": chronos["paths_uri"],
    })
    baseline_metrics = yield from runner.call("price_book", {
        **execution,
        "paths_uri": baseline["paths_uri"],
    }, expected_source="parametric", expected_role="baseline")
    chronos_metrics = yield from runner.call("price_book", {
        **execution,
        "paths_uri": chronos["paths_uri"],
    }, expected_source=(
        "chronos2_conditional" if spec.conditioning else "chronos2"
    ), expected_role="chronos_only")
    augmented_metrics = yield from runner.call("price_book", {
        **execution,
        "paths_uri": blend["blended_uri"],
    }, expected_source="blended", expected_role="augmented")
    pfe_plot = yield from runner.call("plot", {
        **execution,
        "spec": "pfe_overlay",
        "baseline_uri": baseline_metrics["metrics_uri"],
        "augmented_uri": augmented_metrics["metrics_uri"],
    }, expected_plot_role="pfe_overlay")
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
