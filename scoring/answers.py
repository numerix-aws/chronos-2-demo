"""Answer-quality dispatch: reuses the reflexion/react oracles per turn kind."""
import bridge

_ACK_WORDS = ("no completed run", "cannot", "can't", "unable", "not able",
              "failed", "out of scope", "does not", "doesn't", "run one",
              "no run")
_PREMISE_OK = ("augment",)
_PREMISE_CORRECTION = ("not replace", "never replace", "doesn't replace",
                       "does not replace", "isn't a replacement",
                       "is not a replacement")


def _numbers(text: str) -> list[float]:
    return (bridge.reflexion_validator.extract_money(text)
            + bridge.reflexion_validator.extract_percents(text))


def _refusal(text: str) -> dict:
    violations = []
    if _numbers(text):
        violations.append({"type": "refusal_with_numbers",
                           "detail": "refusal/redirect contains numeric claims"})
    if not any(w in text.lower() for w in _ACK_WORDS):
        violations.append({"type": "missing_limitation",
                           "detail": "no acknowledgement of what cannot be answered"})
    return {"passed": not violations, "violations": violations}


def _chat(text: str) -> dict:
    violations = []
    if _numbers(text):
        violations.append({"type": "fabricated_quant",
                           "detail": "small talk answered with quantitative claims"})
    return {"passed": not violations, "violations": violations}


def _premise(text: str) -> list:
    lower = text.lower()
    corrected = (any(w in lower for w in _PREMISE_OK)
                 and any(w in lower for w in _PREMISE_CORRECTION))
    if corrected:
        return []
    return [{"type": "premise_not_corrected",
             "detail": "answer does not correct 'Chronos-2 replaced MC'"}]


def score(kind: str, text: str, *, fixture=None, bundle=None, trace=None) -> dict:
    if kind == "none":
        return {"passed": True, "violations": []}
    if kind == "refusal":
        return _refusal(text)
    if kind == "chat":
        return _chat(text)
    if kind == "narration":
        violations = bridge.reflexion_validator.validate(text, fixture)
        return {"passed": not violations, "violations": violations}
    if kind == "triage":
        return bridge.react_oracle_triage.score(text, bundle)
    if kind in ("qa", "qa_premise"):
        result = bridge.react_oracle_drilldown.score(text, bundle, trace)
        violations = list(result["violations"])
        if kind == "qa_premise":
            violations += _premise(text)
        return {"passed": not violations, "violations": violations}
    raise KeyError(kind)
