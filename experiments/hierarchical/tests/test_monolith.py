import json

import bridge
import monolith
import specialists


def test_system_prompt_covers_all_duties():
    text = monolith.MONOLITH_SYSTEM.lower()
    for duty in ("clarify", "narrat", "triage", "refus", "caveat"):
        assert duty in text


def test_turn_prompt_stuffs_transcript_and_bundle():
    bundle = bridge.load_react_bundle("drilldown_happy")
    transcript = [{"role": "user", "text": "run it"},
                  {"role": "assistant", "text": "done, PFE is up"}]
    prompt = monolith.build_turn_prompt(transcript, bundle, "why did PFE move?")
    assert "run it" in prompt and "done, PFE is up" in prompt
    assert "why did PFE move?" in prompt
    assert json.dumps(bundle["run_spec"], sort_keys=True)[:40] in prompt


def test_turn_prompt_without_bundle_says_so():
    prompt = monolith.build_turn_prompt([], None, "why did PFE move?")
    assert "no completed run" in prompt.lower()


def test_tool_surface_grows_with_bundle():
    trace = bridge.react_trace.Trace()
    fixture = specialists.default_clarify_fixture("run it")
    _, state, _ = monolith.make_monolith_agent(
        fixture, None, trace, respond=lambda q: "ok")
    assert state["compiled"] is None
    agent_no_bundle, _, _ = monolith.make_monolith_agent(
        fixture, None, trace, respond=lambda q: "ok")
    bundle = bridge.load_react_bundle("drilldown_happy")
    agent_with_bundle, _, _ = monolith.make_monolith_agent(
        fixture, bundle, trace, respond=lambda q: "ok")
    assert len(monolith.tool_names(agent_with_bundle)) == 9
    assert len(monolith.tool_names(agent_no_bundle)) == 3
