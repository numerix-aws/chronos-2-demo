import bridge
import specialists


def test_allowlists_match_spec():
    assert specialists.ALLOWLISTS == {
        "clarifier": frozenset(("get_approved_defaults", "ask_user", "compile_spec")),
        "qa": frozenset(("list_events", "get_event", "get_run_spec",
                         "get_artifact_manifest", "get_task_status",
                         "get_diagnostics")),
        "triage": frozenset(("list_events", "get_event", "get_run_spec",
                             "get_artifact_manifest", "get_task_status",
                             "get_diagnostics")),
        "direct": frozenset(),
        "refuse": frozenset(),
    }


def test_clarifier_construction_is_offline_and_returns_react_state():
    trace = bridge.react_trace.Trace()
    fixture = specialists.default_clarify_fixture("Run the COVID scenario")
    agent, state, sim = specialists.make_clarifier(
        fixture, trace, respond=lambda q: "no preference")
    assert set(state) == {"questions", "compiled"}
    assert state["compiled"] is None and state["questions"] == []
    assert sim is not None


def test_default_clarify_fixture_shape():
    fx = specialists.default_clarify_fixture("run it")
    assert fx["prompt"] == "run it"
    assert fx["hidden_intent"] == {} and fx["must_resolve"] == []


def test_qa_and_triage_share_tools_but_not_prompts():
    trace = bridge.react_trace.Trace()
    bundle = bridge.load_react_bundle("drilldown_happy")
    qa = specialists.make_specialist("qa", bundle, trace)
    triage = specialists.make_specialist("triage", bundle, trace)
    assert qa.system_prompt != triage.system_prompt
    for prompt in (qa.system_prompt, triage.system_prompt):
        assert "never" in prompt.lower() or "not" in prompt.lower()  # no rerun/mutate


def test_direct_prompt_carries_state_and_forbids_numbers():
    text = specialists.build_direct_prompt(
        "just give me the PFE number", "active run: failed (exec exec-1)", "refuse")
    assert "active run: failed (exec exec-1)" in text
    assert "just give me the PFE number" in text
    assert "no numeric" in text.lower() or "no numbers" in text.lower()
    redirect = specialists.build_direct_prompt("hi", "active run: none", "direct")
    assert redirect != text
