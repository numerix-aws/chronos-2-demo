import pytest

import director
import sessions


def _state(status: str) -> director.DirectorState:
    return director.DirectorState(run_status=status)


# (intent, run_status) -> expected route. This IS the spec §2 table.
MATRIX = {
    ("quant_run", "none"): "clarifier",
    ("quant_run", "complete"): "clarifier",
    ("quant_run", "failed"): "clarifier",
    ("what_if", "none"): "clarifier",
    ("what_if", "complete"): "clarifier",
    ("what_if", "failed"): "clarifier",
    ("followup_qa", "none"): "refuse",
    ("followup_qa", "complete"): "qa",
    ("followup_qa", "failed"): "refuse",
    ("failure_help", "none"): "refuse",
    ("failure_help", "complete"): "qa",
    ("failure_help", "failed"): "triage",
    ("out_of_scope", "none"): "direct",
    ("out_of_scope", "complete"): "direct",
    ("out_of_scope", "failed"): "direct",
    ("general_chat", "none"): "direct",
    ("general_chat", "complete"): "direct",
    ("general_chat", "failed"): "direct",
}


def test_matrix_is_total():
    assert set(MATRIX) == {(i, s) for i in sessions.INTENTS
                           for s in ("none", "complete", "failed")}


@pytest.mark.parametrize("cell,expected", sorted(MATRIX.items()))
def test_route(cell, expected):
    intent, status = cell
    assert director.route(intent, _state(status)) == expected


def test_route_rejects_unknown_intent():
    with pytest.raises(KeyError):
        director.route("baseline_agent", _state("none"))


def test_apply_outcome_complete():
    bundle = {"run_spec": {"execution_id": "exec-1", "spec_hash": "abc"},
              "diagnostics": {"factor_coverage": {}}}
    state = director.apply_outcome(
        director.DirectorState(), bundle, {"workflow": {}}, "complete")
    assert state.run_status == "complete"
    assert state.execution_id == "exec-1" and state.spec_hash == "abc"
    assert state.bundle is bundle and state.diagnostics_ok is True


def test_apply_outcome_failed_clears_narration_fixture():
    bundle = {"run_spec": {"execution_id": "exec-2", "spec_hash": "def"},
              "diagnostics": {}}
    state = director.apply_outcome(director.DirectorState(), bundle, None, "failed")
    assert state.run_status == "failed" and state.fixture is None
    assert state.diagnostics_ok is False


def test_summary_mentions_status_and_id():
    state = director.apply_outcome(
        director.DirectorState(),
        {"run_spec": {"execution_id": "exec-3", "spec_hash": "aaa"},
         "diagnostics": {"factor_coverage": {}}},
        {"workflow": {}}, "complete")
    assert "complete" in state.summary() and "exec-3" in state.summary()
    assert "none" in director.DirectorState().summary()
