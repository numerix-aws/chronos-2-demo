"""Drilldown-role oracle (spec §6): reflexion faithfulness + grounding."""
from oracles._bridge import validator


def _fixture_view(bundle: dict) -> dict:
    return {
        "expected_posture": bundle.get("expected_posture", "full"),
        "defect": bundle.get("defect"),
        "workflow": {
            "run_spec": bundle["run_spec"],
            "exposure": bundle["exposure"],
            "diagnostics": bundle["diagnostics"],
        },
    }


def _observed_with_scales(trace) -> set[float]:
    observed = trace.observed_numbers()
    # Unit-interval fractions may be cited as percentages (coverage, w_stress).
    observed |= {v * 100.0 for v in set(observed) if 0.0 <= v <= 1.0}
    return observed


def grounding_violations(text: str, trace) -> list[dict]:
    observed = _observed_with_scales(trace)
    violations = []
    claims = ([("money", c) for c in validator.extract_money(text)]
              + [("percent", c) for c in validator.extract_percents(text)])
    for kind, claim in claims:
        if any(abs(claim - v) <= validator.REL_TOL * max(abs(v), 1e-12)
               for v in observed):
            continue
        violations.append({
            "type": "ungrounded_claim",
            "detail": f"{kind} claim {claim} never appeared in a fetched "
                      "tool observation",
        })
    return violations


def score(text: str, bundle: dict, trace=None) -> dict:
    violations = validator.validate(text, _fixture_view(bundle))
    if trace is not None:
        violations = violations + grounding_violations(text, trace)
    return {"passed": not violations, "violations": violations}
