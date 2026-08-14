import scenarios
from run_experiment import merge_summary, summarize


def test_matrix_sizes_match_spec():
    assert len(scenarios.CLARIFY) == 6
    assert len(scenarios.TRIAGE) == 5
    assert len(scenarios.DRILLDOWN) == 5


def test_all_scenarios_load():
    for name in scenarios.CLARIFY:
        fixture = scenarios.load_clarify(name)
        assert fixture["prompt"] and fixture["expected_posture"]
    for name in scenarios.TRIAGE:
        bundle = scenarios.load_triage(name)
        assert bundle["expected_posture"] == "degraded"
        assert bundle["ground_truth"]["defect"] == name
    for item in scenarios.DRILLDOWN:
        bundle, question = scenarios.load_drilldown(item)
        assert bundle["expected_posture"] == "full" and question


def test_summarize_aggregates_per_role_and_arm():
    records = [
        {"role": "triage", "arm": "a", "passed": True, "tool_calls": 0,
         "output_tokens": 100, "latency_s": 1.0, "error": None},
        {"role": "triage", "arm": "a", "passed": False, "tool_calls": 0,
         "output_tokens": 300, "latency_s": 3.0, "error": None},
        {"role": "triage", "arm": "b", "passed": True, "tool_calls": 4,
         "output_tokens": 200, "latency_s": 2.0, "error": None},
        {"role": "triage", "arm": "b", "passed": None, "tool_calls": 0,
         "output_tokens": None, "latency_s": 0.0, "error": "boom"},
    ]
    summary = summarize(records)
    cell_a = summary["triage"]["a"]
    assert cell_a["trials"] == 2 and cell_a["pass_rate"] == 0.5
    assert cell_a["mean_output_tokens"] == 200.0
    cell_b = summary["triage"]["b"]
    assert cell_b["trials"] == 2 and cell_b["errors"] == 1
    assert cell_b["pass_rate"] == 1.0  # over scored trials only
    assert cell_b["mean_tool_calls"] == 4.0


def test_summarize_includes_violation_type_breakdown():
    records = [
        {"role": "drilldown", "arm": "b", "passed": False, "tool_calls": 2,
         "output_tokens": 10, "latency_s": 1.0, "error": None,
         "report": {"passed": False, "violations": [
             {"type": "ungrounded_claim", "detail": "x"},
             {"type": "ungrounded_claim", "detail": "y"},
             {"type": "wrong_value", "detail": "z"}]}},
        {"role": "drilldown", "arm": "b", "passed": True, "tool_calls": 1,
         "output_tokens": 10, "latency_s": 1.0, "error": None,
         "report": {"passed": True, "violations": []}},
    ]
    cell = summarize(records)["drilldown"]["b"]
    assert cell["violation_types"] == {"ungrounded_claim": 2, "wrong_value": 1}


def test_merge_summary_updates_only_rerun_roles():
    existing = {"clarify": {"a": {"pass_rate": 0.33}},
                "drilldown": {"a": {"pass_rate": 0.0}}}
    new = {"drilldown": {"a": {"pass_rate": 0.8}, "b": {"pass_rate": 0.9}}}
    merged = merge_summary(existing, new)
    assert merged["clarify"]["a"]["pass_rate"] == 0.33
    assert merged["drilldown"]["a"]["pass_rate"] == 0.8
    assert merged["drilldown"]["b"]["pass_rate"] == 0.9
    assert existing["drilldown"]["a"]["pass_rate"] == 0.0
