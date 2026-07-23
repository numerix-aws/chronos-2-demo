"""Structured Strands events are the runtime-to-UI contract."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path


RUNTIME_DIR = Path(__file__).resolve().parents[1] / "runtime"


def _load_events_module():
    path = RUNTIME_DIR / "events.py"
    assert path.exists(), "runtime event translator has not been implemented"
    spec = importlib.util.spec_from_file_location("runtime_events", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_entrypoint_streams_instead_of_returning_one_agent_result():
    tree = ast.parse((RUNTIME_DIR / "agent.py").read_text())
    invoke = next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "invoke"
    )

    assert isinstance(invoke, ast.AsyncFunctionDef)
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "stream_async"
        for node in ast.walk(invoke)
    )
    assert any(isinstance(node, (ast.Yield, ast.YieldFrom)) for node in ast.walk(invoke))


def test_runtime_image_has_clean_checkout_deterministic_dependencies_only():
    dockerfile = (RUNTIME_DIR / "Dockerfile").read_text()

    for required in (
        "COPY agent/runtime/events.py /app/events.py",
        "COPY agent/runtime/workflow.py /app/workflow.py",
        "COPY src/chronos2_demo/__init__.py /app/chronos2_demo/__init__.py",
        "COPY src/chronos2_demo/run_spec.py /app/chronos2_demo/run_spec.py",
    ):
        assert required in dockerfile
    assert "COPY src/chronos2_demo/ /app/chronos2_demo/" not in dockerfile
    assert 'pip install -e ".[dev]"' not in dockerfile


def test_translator_emits_text_and_deduplicated_tool_lifecycle_events():
    module = _load_events_module()
    translator = module.StrandsEventTranslator()

    assert translator.translate({"data": "Hello"}) == [
        {"type": "text", "text": "Hello"},
    ]

    running = {
        "current_tool_use": {
            "toolUseId": "tool-1",
            "name": "price-book___price_book",
            "input": {"paths_uri": "s3://bucket/baseline.pkl"},
        }
    }
    assert translator.translate(running) == [
        {
            "type": "tool",
            "tool_use_id": "tool-1",
            "name": "price_book",
            "status": "running",
            "input": {"paths_uri": "s3://bucket/baseline.pkl"},
        }
    ]
    assert translator.translate(running) == []

    result = {
        "status": "ok",
        "result": {
            "dates": ["2023-09-18", "2023-09-19"],
            "ee": [100.0, 120.0],
            "pfe_975": [400.0, 490.0],
            "es_975": [500.0, 610.0],
            "metrics_uri": "s3://bucket/metrics.json",
        },
    }
    completed = {
        "message": {
            "role": "user",
            "content": [
                {
                    "toolResult": {
                        "toolUseId": "tool-1",
                        "status": "success",
                        "content": [{"json": result}],
                    }
                }
            ],
        }
    }
    assert translator.translate(completed) == [
        {
            "type": "tool",
            "tool_use_id": "tool-1",
            "name": "price_book",
            "status": "done",
            "result": result,
        }
    ]


def test_translator_marks_failed_tool_results():
    module = _load_events_module()
    translator = module.StrandsEventTranslator()
    translator.translate({
        "current_tool_use": {
            "toolUseId": "tool-2",
            "name": "plot",
            "input": {"spec": "pfe_overlay"},
        }
    })

    events = translator.translate({
        "message": {
            "role": "user",
            "content": [{
                "toolResult": {
                    "toolUseId": "tool-2",
                    "status": "error",
                    "content": [{"text": '{"status":"error","message":"plot failed"}'}],
                }
            }],
        }
    })

    assert events == [{
        "type": "tool",
        "tool_use_id": "tool-2",
        "name": "plot",
        "status": "failed",
        "result": {"status": "error", "message": "plot failed"},
    }]


def test_translator_emits_direct_tool_result_and_ignores_later_duplicate():
    module = _load_events_module()
    translator = module.StrandsEventTranslator()
    translator.translate({
        "current_tool_use": {
            "toolUseId": "tool-3",
            "name": "price_book",
            "input": {},
        }
    })

    result = {"status": "ok", "result": {"dates": ["2023-09-19"], "ee": [120.0]}}
    tool_result = {
        "toolUseId": "tool-3",
        "status": "success",
        "content": [{"json": result}],
    }

    assert translator.translate({
        "type": "tool_result",
        "tool_result": tool_result,
    }) == [{
        "type": "tool",
        "tool_use_id": "tool-3",
        "name": "price_book",
        "status": "done",
        "result": result,
    }]
    assert translator.translate({
        "message": {
            "role": "user",
            "content": [{"toolResult": tool_result}],
        }
    }) == []
