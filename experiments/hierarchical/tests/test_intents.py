import pydantic
import pytest

import intents
import sessions


def test_verdict_schema_matches_session_intents():
    fields = intents.IntentVerdict.model_fields
    assert set(fields) == {"intent", "confidence"}
    literal = fields["intent"].annotation
    assert set(literal.__args__) == set(sessions.INTENTS)


def test_verdict_rejects_unknown_intent():
    with pytest.raises(pydantic.ValidationError):
        intents.IntentVerdict(intent="run_the_dag_yourself", confidence=0.9)


def test_prompt_contains_state_and_all_labels():
    prompt = intents.build_intent_prompt(
        "Why did PFE move?", "active run: complete (exec exec-1)")
    assert "active run: complete (exec exec-1)" in prompt
    assert "Why did PFE move?" in prompt
    for label in sessions.INTENTS:
        assert label in prompt


def test_prompt_forbids_authority():
    prompt = intents.build_intent_prompt("hi", "active run: none")
    assert "classify" in prompt.lower()
    assert "do not answer" in prompt.lower()
