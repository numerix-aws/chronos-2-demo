from types import SimpleNamespace

import director


def _gen(text):
    return SimpleNamespace(text=text, input_tokens=1, output_tokens=1, latency_s=0.0)


def _state():
    return director.DirectorState(
        execution_id="exec-9", spec_hash="cafe1234", run_status="complete")


PASS_VERDICT = SimpleNamespace(passed=True, violations=[])
FAIL_VERDICT = SimpleNamespace(passed=False, violations=[])


def test_converged_narration_publishes_on_narrator_channel():
    pub = director.publish_narration(
        "interpret", {"workflow": {}}, _state(),
        generate_fn=lambda fb: _gen("clean narration"),
        validate_fn=lambda text: [],
        critique_fn=lambda text: PASS_VERDICT)
    assert pub.channel == "narrator" and pub.text == "clean narration"
    assert pub.iterations == 1


def test_nonconverged_falls_to_degraded_when_degraded_is_clean():
    calls = []

    def generate(feedback):
        calls.append(feedback)
        if feedback and director.DEGRADED_INSTRUCTION in feedback:
            return _gen("caveat-first degraded text")
        return _gen("overclaiming narration $9.99M")

    def validate(text):
        return [] if "degraded" in text else [
            {"type": "invented_value", "detail": "$9.99M not in fixture"}]

    pub = director.publish_narration(
        "interpret", {"workflow": {}}, _state(),
        generate_fn=generate, validate_fn=validate,
        critique_fn=lambda text: FAIL_VERDICT)
    assert pub.channel == "degraded"
    assert pub.text == "caveat-first degraded text"
    # 3 loop attempts + 1 degraded attempt
    assert len(calls) == 4
    assert director.DEGRADED_INSTRUCTION in calls[-1]


def test_degraded_failure_falls_to_coded_template():
    violations = [{"type": "invented_value", "detail": "$9.99M not in fixture"}]
    pub = director.publish_narration(
        "interpret", {"workflow": {}}, _state(),
        generate_fn=lambda fb: _gen("always overclaims $9.99M"),
        validate_fn=lambda text: violations,
        critique_fn=lambda text: FAIL_VERDICT)
    assert pub.channel == "template"
    assert pub.text == director.render_failure_template(_state(), violations)


def test_template_is_deterministic_and_grounded():
    violations = [{"type": "wrong_value", "detail": "PFE mismatch"},
                  {"type": "invented_value", "detail": "no counterpart"}]
    text = director.render_failure_template(_state(), violations)
    assert text == director.render_failure_template(_state(), violations)
    assert "exec-9" in text and "cafe1234" in text and "2" in text
    assert "$" not in text  # the template never states result numbers
