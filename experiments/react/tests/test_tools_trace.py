import bundle
from tests.test_bundle import _mini_fixture

import tools
from trace import Trace


def _env():
    trace = Trace()
    b = bundle.build_bundle(_mini_fixture())
    return tools.make_evidence_functions(b, trace), b, trace


def test_six_tools_exposed():
    fns, _, _ = _env()
    assert set(fns) == {"list_events", "get_event", "get_run_spec",
                        "get_artifact_manifest", "get_task_status",
                        "get_diagnostics"}


def test_list_events_is_summary_and_get_event_is_full():
    fns, b, _ = _env()
    summaries = fns["list_events"]()
    assert len(summaries) == len(b["events"])
    assert all("terminal" not in s for s in summaries)
    full = fns["get_event"](7)
    assert full["name"] == "price_book" and full["terminal"]["pfe_975"] == 2.0


def test_get_event_out_of_range_is_error_string():
    fns, _, _ = _env()
    result = fns["get_event"](99)
    assert result == {"error": "no event with seq 99"}


def test_reads_do_not_mutate_bundle():
    fns, b, _ = _env()
    fns["get_run_spec"]()["as_of_date"] = "corrupted"
    fns["get_diagnostics"]()["execution_id"] = "corrupted"
    assert b["run_spec"]["as_of_date"] == "2022-09-30"
    assert b["diagnostics"]["execution_id"] == "e" * 32


def test_trace_records_every_call_in_order():
    fns, _, trace = _env()
    fns["get_run_spec"]()
    fns["get_task_status"]()
    fns["get_event"](0)
    assert trace.tool_names() == ["get_run_spec", "get_task_status", "get_event"]
    assert trace.calls[2]["args"] == {"seq": 0}


def test_observed_numbers_collects_numeric_leaves():
    fns, _, trace = _env()
    fns["get_event"](7)
    observed = trace.observed_numbers()
    assert 2.0 in observed and 3.0 in observed
    boolean_only = Trace()
    boolean_only.record("get_event", {"seq": 5}, {"ready": True, "ok": False})
    assert boolean_only.observed_numbers() == set()


def test_observed_numbers_skip_keys():
    trace = Trace()
    trace.record("x", {}, {"seq": 3, "nested": {"attempt": 4, "v": 5.5}})
    assert trace.observed_numbers() == {3.0, 4.0, 5.5}
    assert trace.observed_numbers(skip_keys={"seq", "attempt"}) == {5.5}


def test_strands_wrapping():
    fns, b, trace = _env()
    wrapped = tools.make_evidence_tools(b, trace)
    assert len(wrapped) == 6
