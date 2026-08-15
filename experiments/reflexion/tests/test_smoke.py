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


import critic  # noqa: E402


def test_critic_prompt_contains_narration_fixture_and_rubric():
    prompt = critic.build_critic_prompt("The PFE rose.", WORKFLOW_FIXTURE)
    assert "The PFE rose." in prompt
    assert '"execution_id": "e1"' in prompt
    assert "augments" in prompt  # narrative rubric present


def test_critic_verdict_schema():
    verdict = critic.CriticVerdict(passed=False, violations=[
        critic.CriticViolation(type="narrative_violation", claim="c", evidence="e"),
    ])
    assert verdict.violations[0].type == "narrative_violation"


import scenarios  # noqa: E402
import run_experiment  # noqa: E402


def test_scenarios_reference_existing_fixtures():
    fixture_dir = pathlib.Path(__file__).resolve().parents[1] / "fixtures"
    for scenario in scenarios.SCENARIOS:
        assert (fixture_dir / scenario["fixture_file"]).exists(), scenario["name"]


def test_summarize_computes_rates_and_critic_prf():
    trials = [
        {"arm": "A", "scenario": "s", "oracle_violations": [{"type": "invented_value"}],
         "critic_passed": False, "iterations": 1, "latency_s": 1.0,
         "input_tokens": 10, "output_tokens": 5, "converged": True},
        {"arm": "A", "scenario": "s", "oracle_violations": [],
         "critic_passed": True, "iterations": 1, "latency_s": 1.0,
         "input_tokens": 10, "output_tokens": 5, "converged": True},
    ]
    summary = run_experiment.summarize(trials)
    arm = summary["A"]
    assert arm["trials"] == 2
    assert arm["oracle_violation_rate"] == 0.5
    assert arm["critic_precision"] == 1.0 and arm["critic_recall"] == 1.0


def test_checkpoint_round_trip(tmp_path):
    chk = tmp_path / "checkpoint.jsonl"
    trial1 = {"arm": "A", "scenario": "s1", "narration": "text", "oracle_violations": [],
              "critic_passed": True, "iterations": 1, "converged": True, "latency_s": 1.0,
              "input_tokens": 10, "output_tokens": 5}
    trial2 = {"arm": "B", "scenario": "s2", "narration": "more text",
              "oracle_violations": [{"type": "invented_value"}], "critic_passed": False,
              "iterations": 2, "converged": False, "latency_s": 2.0,
              "input_tokens": 20, "output_tokens": 10}
    run_experiment.append_checkpoint(chk, trial1)
    run_experiment.append_checkpoint(chk, trial2)
    loaded = run_experiment.load_checkpoint(chk)
    assert len(loaded) == 2
    assert loaded[0]["arm"] == "A" and loaded[0]["scenario"] == "s1"
    assert loaded[1]["arm"] == "B" and loaded[1]["scenario"] == "s2"


def test_checkpoint_skips_corrupt_trailing_line(tmp_path):
    chk = tmp_path / "checkpoint.jsonl"
    trial1 = {"arm": "A", "scenario": "s", "oracle_violations": [], "critic_passed": True,
              "iterations": 1, "converged": True, "latency_s": 1.0,
              "input_tokens": 10, "output_tokens": 5}
    trial2 = {"arm": "B", "scenario": "s", "oracle_violations": [], "critic_passed": True,
              "iterations": 1, "converged": True, "latency_s": 1.0,
              "input_tokens": 10, "output_tokens": 5}
    run_experiment.append_checkpoint(chk, trial1)
    run_experiment.append_checkpoint(chk, trial2)
    # Append corrupt partial line
    with open(chk, "a", encoding="utf-8") as fh:
        fh.write('{"partial')
    loaded = run_experiment.load_checkpoint(chk)
    assert len(loaded) == 2  # Two intact rows, corrupt line skipped
    assert loaded[0]["arm"] == "A"
    assert loaded[1]["arm"] == "B"


def test_completed_per_cell_counts_error_rows():
    trials = [
        {"arm": "A", "scenario": "happy", "oracle_violations": [], "critic_passed": True,
         "iterations": 1, "converged": True, "latency_s": 1.0,
         "input_tokens": 10, "output_tokens": 5},
        {"arm": "A", "scenario": "happy", "error": "NetworkError",
         "oracle_violations": [], "critic_passed": True,
         "iterations": 0, "converged": False, "latency_s": 0.0,
         "input_tokens": 0, "output_tokens": 0},
        {"arm": "B", "scenario": "edge", "oracle_violations": [], "critic_passed": True,
         "iterations": 2, "converged": True, "latency_s": 2.0,
         "input_tokens": 20, "output_tokens": 10},
    ]
    counts = run_experiment.completed_per_cell(trials)
    assert counts[("happy", "A")] == 2  # Includes the error row
    assert counts[("edge", "B")] == 1
