import json
import pathlib

from chronos2_demo.run_spec import PROFILE

from oracles import clarify

_CLARIFY = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "clarify"


def _fixture(name: str) -> dict:
    return json.loads((_CLARIFY / f"{name}.json").read_text())


def _payload(**overrides) -> dict:
    values = {k: v for k, v in PROFILE.items()}
    values.update(overrides)
    values["provenance"] = {"any": "experiment"}
    values["spec_hash"] = "c" * 64
    return values


def _types(report: dict) -> set[str]:
    return {v["type"] for v in report["violations"]}


def test_correct_default_compile_passes():
    outcome = {"compiled": _payload(), "questions": [], "final_text": "done"}
    report = clarify.score(outcome, _fixture("fully_specified"))
    assert report["passed"] and not report["violations"]


def test_unresolved_when_posture_is_compile():
    outcome = {"compiled": None, "questions": [], "final_text": "Please specify"}
    report = clarify.score(outcome, _fixture("fully_specified"))
    assert not report["passed"] and _types(report) == {"unresolved"}


def test_guessed_while_blocked_on_default_date():
    fixture = _fixture("one_field_missing")
    outcome = {"compiled": _payload(), "questions": [], "final_text": "done"}
    report = clarify.score(outcome, fixture)
    assert "guessed_while_blocked" in _types(report)
    good = {"compiled": _payload(as_of_date="2020-03-31"),
            "questions": ["Which exact as-of date?"], "final_text": "done"}
    assert clarify.score(good, fixture)["passed"]


def test_default_drift_detected():
    fixture = _fixture("fully_specified")
    outcome = {"compiled": _payload(horizon=99), "questions": [],
               "final_text": "done"}
    report = clarify.score(outcome, fixture)
    assert "default_drift" in _types(report)


def test_asked_while_not_blocked():
    fixture = _fixture("fully_specified")
    outcome = {"compiled": _payload(), "questions": ["Which book?"],
               "final_text": "done"}
    assert "asked_while_not_blocked" in _types(clarify.score(outcome, fixture))


def test_conditioning_deep_compare():
    fixture = _fixture("whatif_conditioning")
    good = _payload(w_stress=1.0, conditioning={
        "series_shifts": {"EUR_2Y": -0.5, "EUR_5Y": -0.5},
        "n_anchor_days": 10})
    assert clarify.score(
        {"compiled": good, "questions": [], "final_text": "done"}, fixture
    )["passed"]
    bad = _payload(w_stress=1.0, conditioning={
        "series_shifts": {"EUR_2Y": -0.5}, "n_anchor_days": 10})
    report = clarify.score(
        {"compiled": bad, "questions": [], "final_text": "done"}, fixture)
    assert "wrong_field" in _types(report)


def test_premise_correction_required():
    fixture = _fixture("misleading_premise")
    corrected = {"compiled": _payload(), "questions": [],
                 "final_text": "Chronos-2 augments the Monte Carlo engine; "
                               "it does not replace it. I compiled the "
                               "standard augmented run instead."}
    assert clarify.score(corrected, fixture)["passed"]
    silent = {"compiled": _payload(), "questions": [], "final_text": "done"}
    report = clarify.score(silent, fixture)
    assert {"premise_not_corrected", "compiled_false_premise_only"} & _types(report)
