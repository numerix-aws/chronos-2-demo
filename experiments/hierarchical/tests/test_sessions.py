import sessions


def test_eight_sessions_load_and_validate():
    all_sessions = sessions.load_all()
    assert len(all_sessions) == 8
    names = {s["session"] for s in all_sessions}
    assert names == {
        "s1_clean_run_drilldown", "s2_vague_quant", "s3_conditional_whatif",
        "s4_midsession_failure", "s5_qa_without_run", "s6_misleading_premise",
        "s7_degraded_publish", "s8_chat_quant_mix",
    }


def test_every_turn_carries_ground_truth():
    for s in sessions.load_all():
        assert 2 <= len(s["turns"]) <= 4
        for t in s["turns"]:
            assert t["expected_intent"] in sessions.INTENTS
            assert t["expected_route"] in sessions.ROUTES
            assert "expected_state_after" in t
            assert t["score"]["kind"] in {
                "none", "narration", "qa", "qa_premise", "triage", "refusal", "chat"}
            if t["expected_route"] == "clarifier":
                assert "resolves_to" in t


def test_resolver_complete_outcome():
    bundle, fixture, outcome = sessions.resolve_outcome(
        {"outcome": "complete", "react_bundle": "drilldown_happy",
         "reflexion_fixture": "happy_path"})
    assert outcome == "complete"
    assert bundle["run_spec"]["execution_id"]
    assert fixture["workflow"]["run_spec"]["execution_id"]


def test_resolver_failed_outcome_has_no_narration_fixture():
    bundle, fixture, outcome = sessions.resolve_outcome(
        {"outcome": "failed", "react_bundle": "triage_poll_timeout",
         "reflexion_fixture": None})
    assert outcome == "failed" and fixture is None
    assert bundle["defect"] == "poll_timeout"


def test_degraded_session_builds_degraded_fixture():
    s7 = [s for s in sessions.load_all() if s["session"] == "s7_degraded_publish"][0]
    turn = s7["turns"][0]
    bundle, fixture, outcome = sessions.resolve_outcome(turn["resolves_to"])
    assert outcome == "complete"
    assert fixture["expected_posture"] == "degraded"
    assert fixture["defect"] == "hash_mismatch"
    assert "workflow" in fixture
