import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import generator  # noqa: E402

WORKFLOW_FIXTURE = {
    "expected_posture": "full", "defect": None,
    "workflow": {"run_spec": {"execution_id": "e1"}, "exposure": {}, "diagnostics": {}},
}
PARTIAL_FIXTURE = {
    "expected_posture": "degraded", "defect": "partial_events",
    "raw_events_truncated": '{"run_spec": {"execu',
}


def test_build_prompt_matches_production_template():
    prompt = generator.build_prompt("Explain the run.", WORKFLOW_FIXTURE)
    payload = json.dumps(WORKFLOW_FIXTURE["workflow"], sort_keys=True, allow_nan=False)
    assert prompt == (
        "Explain the run.\n\nThe deterministic quantitative workflow completed. "
        f"Interpret these structured results without changing any value: {payload}"
    )


def test_build_prompt_partial_events_passes_raw_truncated_stream():
    prompt = generator.build_prompt("Explain the run.", PARTIAL_FIXTURE)
    assert PARTIAL_FIXTURE["raw_events_truncated"] in prompt
    assert "workflow completed" not in prompt


def test_build_prompt_appends_feedback_block():
    prompt = generator.build_prompt("Explain.", WORKFLOW_FIXTURE, feedback="fix: PFE value wrong")
    assert prompt.endswith(
        "\n\nA reviewer found problems with your previous answer. "
        "Rewrite it, fixing every issue:\nfix: PFE value wrong"
    )


def test_system_prompt_loads_from_production():
    assert len(generator.SYSTEM_PROMPT) > 100
