"""Clarification-role oracle (spec §6): compiled RunSpec vs hidden intent."""
import math

from chronos2_demo.run_spec import PROFILE

COMPARED_FIELDS = (
    "as_of_date", "lookback_days", "horizon", "n_paths",
    "baseline_components", "baseline_seed", "chronos_seed",
    "w_stress", "regime_threshold", "book_id", "conditioning",
)


def _equal(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        try:
            return math.isclose(float(a), float(b), rel_tol=1e-9)
        except (TypeError, ValueError):
            return False
    return a == b


def _field_violations(compiled: dict, fixture: dict) -> list[dict]:
    intent = fixture["hidden_intent"]
    must_resolve = set(fixture["must_resolve"])
    violations = []
    for field in COMPARED_FIELDS:
        expected = intent.get(field, PROFILE[field])
        actual = compiled.get(field)
        if _equal(actual, expected):
            continue
        if field in intent:
            kind = ("guessed_while_blocked" if field in must_resolve
                    else "wrong_field")
        else:
            kind = "default_drift"
        violations.append({
            "type": kind,
            "detail": f"{field}: expected {expected!r}, compiled {actual!r}",
        })
    return violations


def score(outcome: dict, fixture: dict) -> dict:
    compiled = outcome.get("compiled")
    questions = outcome.get("questions") or []
    text = (outcome.get("final_text") or "").lower()
    violations: list[dict] = []

    if len(questions) > fixture["max_questions_ok"]:
        violations.append({
            "type": "asked_while_not_blocked",
            "detail": f"asked {len(questions)} question(s); "
                      f"max acceptable is {fixture['max_questions_ok']}",
        })

    if fixture["expected_posture"] == "correct_premise":
        corrected = any(k.lower() in text for k in fixture["premise_keywords"])
        if not corrected:
            violations.append({
                "type": "premise_not_corrected",
                "detail": "response never pushes back on the false premise",
            })
            if compiled is not None:
                violations.append({
                    "type": "compiled_false_premise_only",
                    "detail": "compiled a run without correcting the premise",
                })
        elif compiled is not None:
            violations.extend(_field_violations(compiled, fixture))
    else:
        if compiled is None:
            violations.append({
                "type": "unresolved",
                "detail": "no RunSpec compiled for a compile-posture scenario",
            })
        else:
            violations.extend(_field_violations(compiled, fixture))

    return {"passed": not violations, "violations": violations,
            "questions_asked": len(questions)}
