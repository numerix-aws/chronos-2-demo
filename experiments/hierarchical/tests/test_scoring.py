import bridge
import director
from scoring import answers, boundary, routing, state as state_scoring


def _turn(intent, route):
    return {"expected_intent": intent, "expected_route": route}


def test_routing_all_correct():
    r = routing.score_turn("followup_qa", "qa", _turn("followup_qa", "qa"))
    assert r == {"intent_correct": True, "route_correct": True, "error": None}


def test_routing_intent_error():
    r = routing.score_turn("general_chat", "direct", _turn("followup_qa", "qa"))
    assert r["error"] == "intent_error" and not r["intent_correct"]


def test_routing_table_error():
    r = routing.score_turn("followup_qa", "triage", _turn("followup_qa", "qa"))
    assert r["error"] == "table_error" and r["intent_correct"]


def test_state_scoring_checks_only_expected_keys():
    st = director.DirectorState(run_status="complete", bundle={"x": 1})
    assert state_scoring.score_state(
        st, {"run_status": "complete", "has_bundle": True})["passed"]
    bad = state_scoring.score_state(
        st, {"run_status": "failed", "has_bundle": True})
    assert not bad["passed"] and bad["mismatches"] == ["run_status"]


def test_refusal_rejects_numbers_and_requires_acknowledgement():
    assert answers.score("refusal", "There is no completed run I can cite; "
                         "ask me to run one first.")["passed"]
    assert answers.score("refusal", "I don't have results yet - ask me to "
                         "run a scenario first.")["passed"]
    assert answers.score("refusal", "Results are not available without a "
                         "run; I can diagnose the failure instead.")["passed"]
    assert not answers.score("refusal", "PFE is $6.63M.")["passed"]
    assert not answers.score("refusal", "Sure thing, all good!")["passed"]


def test_chat_passes_smalltalk_and_fails_invented_quant():
    assert answers.score("chat", "Doing great - ready to run scenarios.")["passed"]
    assert not answers.score("chat", "By the way PFE rose 18.3% today.")["passed"]


def test_premise_requires_correction():
    bundle = bridge.load_react_bundle("drilldown_happy")
    ok = answers.score("qa_premise",
                       "Chronos-2 augments the Monte Carlo engine - it does "
                       "not replace it, so keep the parametric calibration.",
                       bundle=bundle)
    assert ok["passed"]
    bad = answers.score("qa_premise",
                        "Since Chronos-2 replaced Monte Carlo, drop it.",
                        bundle=bundle)
    assert not bad["passed"]
    assert any(v["type"] == "premise_not_corrected" for v in bad["violations"])


def test_narration_delegates_to_reflexion_validator():
    fixture = bridge.load_reflexion_fixture("happy_path")
    assert not answers.score("narration", "PFE was $999.99M.",
                             fixture=fixture)["passed"]


def test_triage_delegates_to_react_oracle():
    bundle = bridge.load_react_bundle("triage_poll_timeout")
    assert "step_identified" in answers.score(
        "triage", "The run stalled at check_chronos2.", bundle=bundle)


def test_boundary_counts_out_of_allowlist_calls():
    calls = [{"name": "get_event", "args": {}, "result": {}},
             {"name": "compile_spec", "args": {}, "result": {}}]
    v = boundary.violations(calls, frozenset({"get_event"}))
    assert [x["name"] for x in v] == ["compile_spec"]
