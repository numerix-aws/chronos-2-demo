"""Drilldown-role oracle v2: bundle-wide faithfulness + evidence grounding.

v2 recalibration (after the 2026-08-13 live run). The reflexion validator's
expected-value set covers only exposure terminals, the PFE delta and
w_stress, so four classes of legitimate claims scored as violations:

- structural percentage labels ("the 97.5% quantile") -> invented_value
- diagnostics-attribution numbers and exposure-series values -> invented_value
- truncated hashes and full-precision decimal fragments -> wrong_identifier
- arithmetic the narration derives from payload values ("48.17% above"),
  absolute-value citations of negative deltas ("a 19.83% reduction"), and
  integer rounding ("24%" for 24.48) -> wrong_value / invented_value

v2 widens the base set to every numeric payload leaf, adds a bounded
derived-candidate set (pairwise percent-changes and ratios over headline
scalars, matched at a much tighter tolerance so the check stays
discriminative), accepts abs-of-negative and round-to-integer citations,
requires a hex letter before treating a token as identifier-like, and
prefix-matches identifiers. The reflexion validator remains the claim
extractor (read-only reuse); the degraded-posture gate is unchanged.
"""
import itertools
import re

from oracles._bridge import validator

# Quantile/nominal labels a narration may cite that are not data values.
STRUCTURAL_PERCENTS = (97.5, 95.0, 5.0, 2.5)
# Event bookkeeping counters must not ground numeric claims.
GROUNDING_SKIP_KEYS = frozenset({"seq", "attempt"})
# Derived arithmetic is quoted precisely; tight tolerance keeps the bounded
# pairwise expansion discriminative instead of vacuous.
DERIVED_REL_TOL = 5e-4
_MAX_DERIVED_OPERANDS = 96
# Reflexion's hex regex also matches long decimal runs (float fragments such
# as 614544536470596); a real hash cite contains at least one a-f letter.
_HEX_TOKEN = re.compile(r"\b(?=[0-9a-f]*[a-f])[0-9a-f]{12,64}\b",
                        re.IGNORECASE)


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


def _collect_numbers(value, out: set) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        out.add(float(value))
    elif isinstance(value, dict):
        for item in value.values():
            _collect_numbers(item, out)
    elif isinstance(value, list):
        for item in value:
            _collect_numbers(item, out)


def _with_citation_variants(values: set[float]) -> set[float]:
    # Negative deltas are cited as positive reductions; unit-interval
    # fractions as percentages.
    out = set(values)
    out |= {abs(v) for v in values if v < 0.0}
    out |= {v * 100.0 for v in out.copy() if 0.0 <= v <= 1.0}
    return out


def _derived_candidates(values: set[float]) -> set[float]:
    operands = sorted((v for v in values if abs(v) > 1e-9),
                      key=lambda v: -abs(v))[:_MAX_DERIVED_OPERANDS]
    derived: set[float] = set()
    for a, b in itertools.permutations(operands, 2):
        derived.add((a - b) / abs(b) * 100.0)
        derived.add(a / b * 100.0)
    return derived


def _headline_scalars(bundle: dict) -> set[float]:
    scalars: set[float] = set()
    for payload in (bundle.get("exposure") or {}).values():
        _collect_numbers(payload.get("terminal"), scalars)
    diagnostics = bundle.get("diagnostics") or {}
    _collect_numbers(diagnostics.get("attribution"), scalars)
    fractions: set[float] = set()
    _collect_numbers(diagnostics, fractions)
    scalars |= {v for v in fractions if 0.0 <= v <= 1.0}
    run_spec = bundle.get("run_spec") or {}
    w_stress = run_spec.get("w_stress")
    if isinstance(w_stress, (int, float)) and not isinstance(w_stress, bool):
        scalars.add(float(w_stress))
    return scalars


def _base_values(bundle: dict) -> set[float]:
    values: set[float] = set(
        validator.expected_values(_fixture_view(bundle)).values())
    _collect_numbers(bundle.get("exposure"), values)
    _collect_numbers(bundle.get("diagnostics"), values)
    return _with_citation_variants(values)


def _within(claim: float, value: float, tolerance: float) -> bool:
    return abs(claim - value) <= tolerance * max(abs(value), 1e-12)


def _claim_matches(claim: float, base: set[float],
                   derived: set[float]) -> bool:
    if any(_within(claim, v, validator.REL_TOL) for v in base):
        return True
    # Structural labels match exactly, never via the integer-rounding rule.
    if any(_within(claim, v, validator.REL_TOL) for v in STRUCTURAL_PERCENTS):
        return True
    if claim == round(claim) and any(abs(claim - v) <= 0.5 for v in base):
        return True
    return any(_within(claim, v, DERIVED_REL_TOL) for v in derived)


def _claim_violations(claims: list[float], base: set[float],
                      derived: set[float], *, kind: str) -> list[dict]:
    violations = []
    for claim in claims:
        if _claim_matches(claim, base, derived):
            continue
        if any(_within(claim, v, validator.WRONG_VALUE_BAND) for v in base):
            violations.append({
                "type": "wrong_value",
                "detail": f"{kind} claim {claim} is near a payload value "
                          "but outside tolerance",
            })
        else:
            violations.append({
                "type": "invented_value",
                "detail": f"{kind} claim {claim} matches no payload or "
                          "derived value",
            })
    return violations


_HEXLIKE_STRING = re.compile(r"^[0-9a-f]{12,64}$", re.IGNORECASE)


def _known_identifiers(bundle: dict) -> set[str]:
    # Any hex-looking string anywhere in the payload is a citable identifier
    # (spec_hash, execution_id, artifact sha256s, run_spec provenance hashes).
    known: set[str] = set()

    def walk(value) -> None:
        if isinstance(value, str):
            if _HEXLIKE_STRING.match(value):
                known.add(value.lower())
            else:
                for token in _HEX_TOKEN.findall(value):
                    known.add(token.lower())
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(bundle)
    return known


def _identifier_violations(text: str, bundle: dict) -> list[dict]:
    known = _known_identifiers(bundle)
    violations = []
    for token in _HEX_TOKEN.findall(text):
        lowered = token.lower()
        if any(identifier.startswith(lowered) for identifier in known):
            continue
        violations.append({
            "type": "wrong_identifier",
            "detail": f"identifier-like token {token} is not a prefix of "
                      "any run artifact identifier",
        })
    return violations


def grounding_violations(text: str, trace) -> list[dict]:
    observed = _with_citation_variants(
        trace.observed_numbers(skip_keys=GROUNDING_SKIP_KEYS))
    derived = _derived_candidates(observed)
    violations = []
    claims = ([("money", c) for c in validator.extract_money(text)]
              + [("percent", c) for c in validator.extract_percents(text)])
    for kind, claim in claims:
        if _claim_matches(claim, observed, derived):
            continue
        violations.append({
            "type": "ungrounded_claim",
            "detail": f"{kind} claim {claim} never appeared in (or derives "
                      "from) a fetched tool observation",
        })
    return violations


def score(text: str, bundle: dict, trace=None) -> dict:
    view = _fixture_view(bundle)
    if view["expected_posture"] == "degraded":
        violations = validator.validate(text, view)
    else:
        base = _base_values(bundle)
        derived = _derived_candidates(_headline_scalars(bundle))
        violations = _claim_violations(
            validator.extract_money(text), base, derived, kind="money")
        violations += _claim_violations(
            validator.extract_percents(text), base, derived, kind="percent")
        violations += _identifier_violations(text, bundle)
    if trace is not None:
        violations = violations + grounding_violations(text, trace)
    return {"passed": not violations, "violations": violations}
