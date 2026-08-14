import json
import pathlib

import bundle
from tests.test_bundle import _mini_fixture

import agents
from oracles import clarify

_CLARIFY = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "clarify"


def _fixture(name: str) -> dict:
    return json.loads((_CLARIFY / f"{name}.json").read_text())


def test_public_view_strips_oracle_labels():
    b = bundle.build_bundle(_mini_fixture())
    b["ground_truth"] = {"defect": "x"}
    view = agents.public_view(b)
    assert set(view) == {"run_spec", "events", "artifact_manifest",
                         "task_status", "exposure", "diagnostics"}


def test_clarify_arm_a_baseline_contrast():
    # Arm A is deterministic and hermetic — score it against the oracle to
    # pin today's behavior per scenario.
    expected = {
        "fully_specified": True,
        "one_field_missing": False,   # silently compiles default date
        "vague_stress": False,        # unresolved Clarification
        "hopelessly_vague": False,    # classified non-quantitative
        "whatif_conditioning": True,
        "misleading_premise": False,  # compiles without premise pushback
    }
    for name, should_pass in expected.items():
        fixture = _fixture(name)
        result = agents.clarify_arm_a(fixture)
        report = clarify.score(result.outcome, fixture)
        assert report["passed"] is should_pass, (name, report["violations"])


def test_clarify_arm_a_guessed_while_blocked_detail():
    fixture = _fixture("one_field_missing")
    report = clarify.score(agents.clarify_arm_a(fixture).outcome, fixture)
    assert any(v["type"] == "guessed_while_blocked"
               for v in report["violations"])


def test_system_prompts_carry_role_rules():
    assert "never replaces" in agents.CLARIFY_SYSTEM
    assert "budget: 2" in agents.CLARIFY_SYSTEM.lower()
    assert "read-only" in agents.TRIAGE_SYSTEM.lower()
    assert "tool result" in agents.DRILLDOWN_SYSTEM.lower()


def test_stuffed_prompts_use_public_view_only():
    b = bundle.build_bundle(_mini_fixture())
    b["ground_truth"] = {"defect": "leak-me"}
    b["defect"] = "leak-me"
    prompt = agents.triage_prompt_a(b)
    assert "leak-me" not in prompt and "run_spec" in prompt
    prompt = agents.drilldown_prompt_a(b, "Why?")
    assert "leak-me" not in prompt and prompt.startswith("Why?")
