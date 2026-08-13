import json
import pathlib

import clarify_tools
from sim_user import SimUser
from trace import Trace

_CLARIFY = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "clarify"


def _sim(name: str, respond) -> SimUser:
    fixture = json.loads((_CLARIFY / f"{name}.json").read_text())
    return SimUser(fixture, respond=respond)


def _fns(respond=lambda q: "March 31, 2020"):
    trace = Trace()
    sim = _sim("one_field_missing", respond)
    fns, state = clarify_tools.make_clarify_functions(sim, trace)
    return fns, state, trace, sim


def test_dummy_provenance_has_all_fourteen_keys():
    assert len(clarify_tools.DUMMY_PROVENANCE) == 14
    assert set(clarify_tools.DUMMY_PROVENANCE.values()) == {"experiment"}


def test_defaults_tool_returns_profile():
    fns, _, _, _ = _fns()
    defaults = fns["get_approved_defaults"]()
    assert defaults["as_of_date"] == "2022-09-30"
    assert defaults["w_stress"] == 0.5305


def test_ask_user_routes_to_sim_and_caps_at_two():
    fns, state, _, sim = _fns()
    assert fns["ask_user"]("Which as-of date?") == "March 31, 2020"
    fns["ask_user"]("Which horizon?")
    third = fns["ask_user"]("Which book?")
    assert "no more questions" in third.lower()
    assert state["questions"] == ["Which as-of date?", "Which horizon?"]
    assert len(sim.transcript) == 2


def test_compile_spec_success_records_state():
    fns, state, _, _ = _fns()
    result = fns["compile_spec"](
        "Run the stage-safe headline demo as of 2020-03-31.")
    assert result["compiled"] is True
    assert result["payload"]["as_of_date"] == "2020-03-31"
    assert result["spec_hash"] == result["payload"]["spec_hash"]
    assert state["compiled"] == result["payload"]


def test_compile_spec_failure_reports_missing_fields():
    fns, state, _, _ = _fns()
    result = fns["compile_spec"]("Run a stress scenario on the book.")
    assert result["compiled"] is False and result["is_quantitative"] is True
    assert "as_of_date" in result["missing_fields"]
    assert state["compiled"] is None


def test_all_calls_traced():
    fns, _, trace, _ = _fns()
    fns["get_approved_defaults"]()
    fns["ask_user"]("Which as-of date?")
    fns["compile_spec"]("Run the stage-safe headline demo.")
    assert trace.tool_names() == ["get_approved_defaults", "ask_user",
                                  "compile_spec"]


def test_sim_user_prompt_carries_intent_and_rules():
    sim = _sim("one_field_missing", respond=None)
    prompt = sim.system_prompt()
    assert "2020-03-31" in prompt and "as_of_date" in prompt
    assert "standard setup" in prompt
