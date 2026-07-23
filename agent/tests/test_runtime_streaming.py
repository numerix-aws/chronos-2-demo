"""Structured Strands events are the runtime-to-UI contract."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path


RUNTIME_DIR = Path(__file__).resolve().parents[1] / "runtime"
SPEC_HASH = "c" * 64


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
            "name": "plot-tools___plot",
            "input": {"spec": "pfe_overlay"},
        }
    }
    assert translator.translate(running) == [
        {
            "type": "tool",
            "tool_use_id": "tool-1",
            "name": "plot",
            "status": "running",
            "input": {"spec": "pfe_overlay"},
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
            "name": "plot",
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
            "name": "plot",
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
        "name": "plot",
        "status": "done",
        "result": result,
    }]
    assert translator.translate({
        "message": {
            "role": "user",
            "content": [{"toolResult": tool_result}],
        }
    }) == []


def test_completion_name_cannot_replace_tool_use_identity():
    module = _load_events_module()
    translator = module.StrandsEventTranslator()
    _start(translator, "tool-identity", "plot", {"spec": "pfe_overlay"})
    envelope = {"status": "ok", "result": {"image_uri": "https://example.test/plot.png"}}

    events = translator.translate({
        "tool_result": {
            "toolUseId": "tool-identity",
            "name": "price_book",
            "status": "success",
            "content": [{"json": envelope}],
        }
    })

    assert events == [{
        "type": "tool",
        "tool_use_id": "tool-identity",
        "name": "plot",
        "status": "done",
        "result": envelope,
    }]


def test_duplicate_plot_start_cannot_replace_first_price_book_binding():
    module = _load_events_module()
    translator = module.StrandsEventTranslator()
    paths_uri = "s3://chronos-data/runs/run-1/baseline.pkl"

    assert _start(
        translator,
        "immutable-price",
        "price_book",
        {"execution_id": "run-1", "paths_uri": paths_uri},
    )[0]["name"] == "price_book"
    assert _start(
        translator,
        "immutable-price",
        "plot",
        {"spec": "pfe_overlay"},
    ) == []

    events = _complete(
        translator,
        "immutable-price",
        _price_result(paths_uri=paths_uri),
    )

    assert [event["type"] for event in events] == ["tool", "exposure_result"]
    assert events[0]["name"] == "price_book"
    assert events[0]["status"] == "done"
    assert events[1]["paths_uri"] == paths_uri


def test_first_attempt_input_is_snapshotted_before_external_mutation():
    module = _load_events_module()
    translator = module.StrandsEventTranslator()
    paths_uri = "s3://chronos-data/runs/run-1/baseline.pkl"
    tool_input = {"execution_id": "run-1", "paths_uri": paths_uri}

    _start(translator, "snapshot-price", "price_book", tool_input)
    tool_input["paths_uri"] = "s3://chronos-data/runs/run-1/blended.pkl"

    events = _complete(
        translator,
        "snapshot-price",
        _price_result(paths_uri=paths_uri),
    )

    assert [event["type"] for event in events] == ["tool", "exposure_result"]
    assert events[0]["status"] == "done"


def test_duplicate_price_book_start_cannot_replace_first_plot_binding():
    module = _load_events_module()
    translator = module.StrandsEventTranslator()
    envelope = {"status": "ok", "result": {"image_uri": "https://example.test/plot.png"}}

    assert _start(
        translator,
        "immutable-plot",
        "plot",
        {"spec": "pfe_overlay"},
    )[0]["name"] == "plot"
    assert _start(
        translator,
        "immutable-plot",
        "price_book",
        {
            "execution_id": "run-1",
            "paths_uri": "s3://chronos-data/runs/run-1/baseline.pkl",
        },
    ) == []

    assert _complete(translator, "immutable-plot", envelope) == [{
        "type": "tool",
        "tool_use_id": "immutable-plot",
        "name": "plot",
        "status": "done",
        "result": envelope,
    }]


def test_invalid_start_does_not_claim_attempt_binding():
    module = _load_events_module()
    translator = module.StrandsEventTranslator()

    assert translator.translate({
        "current_tool_use": {
            "toolUseId": "valid-after-invalid",
            "name": "plot",
            "input": [],
        }
    }) == []
    assert translator.translate({
        "current_tool_use": {
            "toolUseId": "valid-after-invalid",
            "name": "gateway___",
            "input": {"spec": "pfe_overlay"},
        }
    }) == []
    assert _start(
        translator,
        "valid-after-invalid",
        "price_book",
        {
            "execution_id": "run-1",
            "paths_uri": "s3://chronos-data/runs/run-1/baseline.pkl",
        },
    )[0]["name"] == "price_book"


def _price_result(
    *,
    role="baseline",
    source="parametric",
    paths_uri="s3://chronos-data/runs/run-1/baseline.pkl",
):
    return {
        "status": "ok",
        "result": {
            "execution_id": "run-1",
            "spec_hash": SPEC_HASH,
            "scenario_role": role,
            "source": source,
            "paths_uri": paths_uri,
            "paths_sha256": "a" * 64,
            "ee": [400000.0, 450586.45],
            "pfe_975": [4800000.0, 4901670.11],
            "es_975": [5700000.0, 5828331.63],
            "dates": ["2023-09-18", "2023-09-19"],
            "terminal": {
                "date": "2023-09-19",
                "ee": 450586.45,
                "pfe_975": 4901670.11,
                "es_975": 5828331.63,
            },
            "metrics_uri": f"s3://chronos-data/runs/run-1/metrics/{role}.json",
            "metrics_sha256": "b" * 64,
        },
    }


def _blend_result():
    return {
        "status": "ok",
        "result": {
            "execution_id": "run-1",
            "spec_hash": SPEC_HASH,
            "blended_uri": "s3://chronos-data/runs/run-1/blended.pkl",
            "blended_sha256": "d" * 64,
            "diagnostics_uri": "s3://chronos-data/runs/run-1/diagnostics.json",
            "diagnostics_sha256": "e" * 64,
            "diagnostics": {
                "execution_id": "run-1",
                "spec_hash": SPEC_HASH,
                "attribution": {"distribution_count": 5},
                "portfolio_coverage": {"available": True},
                "factor_coverage": {"available": True},
            },
            "w_stress": 0.35,
            "n_paths": 5000,
        },
    }


def _start(translator, tool_use_id, name, tool_input):
    return translator.translate({
        "current_tool_use": {
            "toolUseId": tool_use_id,
            "name": name,
            "input": tool_input,
        }
    })


def _complete(translator, tool_use_id, envelope, *, direct=False):
    result = {
        "toolUseId": tool_use_id,
        "status": "success",
        "content": [{"json": envelope}],
    }
    if direct:
        return translator.translate({"tool_result": result})
    return translator.translate({
        "message": {
            "role": "user",
            "content": [{"toolResult": result}],
        }
    })


def test_price_book_done_is_followed_by_one_identity_bearing_exposure_result():
    module = _load_events_module()
    translator = module.StrandsEventTranslator()
    paths_uri = "s3://chronos-data/runs/run-1/baseline.pkl"
    _start(
        translator,
        "price-1",
        "price-book___price_book",
        {"execution_id": "run-1", "paths_uri": paths_uri},
    )
    envelope = _price_result(paths_uri=paths_uri)

    events = _complete(translator, "price-1", envelope)

    assert events == [
        {
            "type": "tool",
            "tool_use_id": "price-1",
            "name": "price_book",
            "status": "done",
            "result": envelope,
        },
        {
            "type": "exposure_result",
            "execution_id": "run-1",
            "spec_hash": SPEC_HASH,
            "scenario_role": "baseline",
            "source": "parametric",
            "paths_uri": paths_uri,
            "paths_sha256": "a" * 64,
            "metrics_uri": "s3://chronos-data/runs/run-1/metrics/baseline.json",
            "metrics_sha256": "b" * 64,
            "terminal": {
                "date": "2023-09-19",
                "ee": 450586.45,
                "pfe_975": 4901670.11,
                "es_975": 5828331.63,
            },
        },
    ]
    assert _complete(translator, "price-1", envelope, direct=True) == []


def test_blend_paths_done_is_followed_by_one_identity_bearing_diagnostics_event():
    module = _load_events_module()
    translator = module.StrandsEventTranslator()
    _start(
        translator,
        "blend-1",
        "blend_paths",
        {"execution_id": "run-1"},
    )
    envelope = _blend_result()

    events = _complete(translator, "blend-1", envelope, direct=True)

    assert events == [
        {
            "type": "tool",
            "tool_use_id": "blend-1",
            "name": "blend_paths",
            "status": "done",
            "result": envelope,
        },
        {
            "type": "diagnostics",
            "execution_id": "run-1",
            "spec_hash": SPEC_HASH,
            "diagnostics_uri": "s3://chronos-data/runs/run-1/diagnostics.json",
            "diagnostics_sha256": "e" * 64,
            "diagnostics": envelope["result"]["diagnostics"],
        },
    ]
    assert _complete(translator, "blend-1", envelope) == []


def test_distinct_price_book_attempts_preserve_each_scenario_role():
    module = _load_events_module()
    translator = module.StrandsEventTranslator()
    cases = (
        ("price-baseline", "baseline", "parametric", "baseline.pkl"),
        ("price-augmented", "augmented", "blended", "blended.pkl"),
    )
    events = []
    for tool_use_id, role, source, filename in cases:
        paths_uri = f"s3://chronos-data/runs/run-1/{filename}"
        _start(
            translator,
            tool_use_id,
            "price_book",
            {"execution_id": "run-1", "paths_uri": paths_uri},
        )
        events.extend(_complete(
            translator,
            tool_use_id,
            _price_result(role=role, source=source, paths_uri=paths_uri),
        ))

    assert [
        event["scenario_role"]
        for event in events
        if event["type"] == "exposure_result"
    ] == ["baseline", "augmented"]
    assert [
        event["tool_use_id"]
        for event in events
        if event["type"] == "tool" and event["status"] == "done"
    ] == ["price-baseline", "price-augmented"]


def test_failed_structured_tool_attempt_emits_lifecycle_failure_only():
    module = _load_events_module()
    translator = module.StrandsEventTranslator()
    _start(
        translator,
        "price-failed",
        "price_book",
        {
            "execution_id": "run-1",
            "paths_uri": "s3://chronos-data/runs/run-1/baseline.pkl",
        },
    )

    events = translator.translate({
        "tool_result": {
            "toolUseId": "price-failed",
            "status": "error",
            "content": [{"json": {"status": "error", "message": "pricing failed"}}],
        }
    })

    assert events == [{
        "type": "tool",
        "tool_use_id": "price-failed",
        "name": "price_book",
        "status": "failed",
        "result": {"status": "error", "message": "pricing failed"},
    }]


def test_malformed_nominally_ok_price_book_result_is_failed_before_summary():
    module = _load_events_module()
    mutations = (
        lambda result: result.pop("metrics_sha256"),
        lambda result: result.__setitem__("execution_id", "run-2"),
        lambda result: result.__setitem__("spec_hash", "not-a-spec-hash"),
        lambda result: result.__setitem__("scenario_role", "augmented"),
        lambda result: (
            result.__setitem__("source", "chronos2"),
            result.__setitem__("scenario_role", "chronos_only"),
        ),
        lambda result: result.__setitem__(
            "metrics_uri",
            "s3://chronos-data/runs/run-1/metrics/augmented.json",
        ),
        lambda result: result["terminal"].__setitem__("ee", "450586.45"),
        lambda result: result["terminal"].__setitem__("ee", 1.0),
        lambda result: result["ee"].__setitem__(1, float("nan")),
    )

    for index, mutate in enumerate(mutations):
        translator = module.StrandsEventTranslator()
        tool_use_id = f"malformed-price-{index}"
        paths_uri = "s3://chronos-data/runs/run-1/baseline.pkl"
        _start(
            translator,
            tool_use_id,
            "price_book",
            {"execution_id": "run-1", "paths_uri": paths_uri},
        )
        envelope = _price_result(paths_uri=paths_uri)
        mutate(envelope["result"])

        events = _complete(translator, tool_use_id, envelope)

        assert len(events) == 1
        assert events[0]["type"] == "tool"
        assert events[0]["status"] == "failed"
        assert events[0]["result"]["status"] == "error"


def test_price_book_terminal_requires_exact_keys_canonical_date_and_finite_numbers():
    module = _load_events_module()

    def set_date(result, value):
        result["dates"][-1] = value
        result["terminal"]["date"] = value

    mutations = (
        lambda result: result["terminal"].__setitem__("extra", 1),
        lambda result: result["terminal"].pop("es_975"),
        lambda result: set_date(result, "2023-02-29"),
        lambda result: set_date(result, "2023-9-19"),
        lambda result: result["terminal"].__setitem__("pfe_975", float("inf")),
    )

    for index, mutate in enumerate(mutations):
        translator = module.StrandsEventTranslator()
        tool_use_id = f"invalid-terminal-{index}"
        paths_uri = "s3://chronos-data/runs/run-1/baseline.pkl"
        _start(
            translator,
            tool_use_id,
            "price_book",
            {"execution_id": "run-1", "paths_uri": paths_uri},
        )
        envelope = _price_result(paths_uri=paths_uri)
        mutate(envelope["result"])

        events = _complete(translator, tool_use_id, envelope)

        assert len(events) == 1
        assert events[0]["type"] == "tool"
        assert events[0]["status"] == "failed"
        assert events[0]["result"]["status"] == "error"


def test_malformed_nominally_ok_blend_result_is_failed_before_diagnostics():
    module = _load_events_module()
    mutations = (
        lambda result: result.pop("diagnostics_sha256"),
        lambda result: result.__setitem__("execution_id", "run-2"),
        lambda result: result.__setitem__("spec_hash", 7),
        lambda result: result["diagnostics"].__setitem__("execution_id", "run-2"),
        lambda result: result["diagnostics"].__setitem__("spec_hash", "other"),
        lambda result: result.__setitem__(
            "diagnostics_uri",
            "s3://chronos-data/runs/run-1/other-diagnostics.json",
        ),
        lambda result: result.__setitem__(
            "blended_uri",
            "s3://chronos-data/runs/run-1/other.pkl",
        ),
        lambda result: result["diagnostics"].__setitem__("bad", float("inf")),
    )

    for index, mutate in enumerate(mutations):
        translator = module.StrandsEventTranslator()
        tool_use_id = f"malformed-blend-{index}"
        _start(
            translator,
            tool_use_id,
            "blend_paths",
            {"execution_id": "run-1"},
        )
        envelope = _blend_result()
        mutate(envelope["result"])

        events = _complete(translator, tool_use_id, envelope)

        assert len(events) == 1
        assert events[0]["type"] == "tool"
        assert events[0]["status"] == "failed"
        assert events[0]["result"]["status"] == "error"


def test_translator_does_not_reinterpret_deterministic_specialized_events():
    module = _load_events_module()
    translator = module.StrandsEventTranslator()

    assert translator.translate({
        "type": "exposure_result",
        **_price_result()["result"],
    }) == []
    assert translator.translate({
        "type": "diagnostics",
        **_blend_result()["result"],
    }) == []
