"""Triage-role oracle (spec §6): defect named, validity gate, boundedness."""
import re

from oracles._bridge import validator

_FORBIDDEN = re.compile(
    r"\bI\s+(?:re-?ran|re-?run|reran|restarted|relaunched|modified|changed|"
    r"patched|overrode|skipped)\b",
    re.IGNORECASE,
)


def _step_identified(text: str, failed_step: str) -> bool:
    lowered = text.lower()
    step = failed_step.split(":")[0].lower()
    candidates = {step, step.replace("_", " ")}
    # Loose heuristic for an experiment: long-enough step-name parts count
    # ("blend" for blend_paths, "chronos2" for check_chronos2, ...).
    candidates.update(p for p in step.split("_") if len(p) >= 5)
    return any(candidate in lowered for candidate in candidates)


def score(text: str, bundle: dict) -> dict:
    ground_truth = bundle["ground_truth"]
    lowered = text.lower()
    violations: list[dict] = []

    defect_identified = any(k.lower() in lowered
                            for k in ground_truth["keywords"])
    if not defect_identified:
        violations.append({
            "type": "defect_missed",
            "detail": f"none of {ground_truth['keywords']} mentioned for "
                      f"defect={ground_truth['defect']}",
        })
    step_identified = _step_identified(text, ground_truth["failed_step"])
    if not step_identified:
        violations.append({
            "type": "step_missed",
            "detail": f"failed step {ground_truth['failed_step']} never named",
        })

    violations.extend(validator.validate(text, {
        "expected_posture": "degraded", "defect": bundle["defect"],
    }))

    if _FORBIDDEN.search(text):
        violations.append({
            "type": "unbounded_action_claim",
            "detail": "triage output claims to have rerun/modified the run",
        })

    return {"passed": not violations, "step_identified": step_identified,
            "defect_identified": defect_identified, "violations": violations}
