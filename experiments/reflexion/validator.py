"""Layer-1 deterministic oracle (spec §5): numeric + structural narration checks."""
import re

REL_TOL = 0.005          # 0.5% relative tolerance for a claim to match
WRONG_VALUE_BAND = 0.10  # within 10% of an expected value but outside tol -> wrong_value

_MONEY = re.compile(
    r"\$\s?([\d,]+(?:\.\d+)?)\s*(million|mio|mn|m|bn|billion|k|thousand)?\b",
    re.IGNORECASE,
)
_PERCENT = re.compile(r"(-?[\d,]+(?:\.\d+)?)\s?%")
_SCALE = {
    None: 1.0, "k": 1e3, "thousand": 1e3,
    "m": 1e6, "mn": 1e6, "mio": 1e6, "million": 1e6,
    "bn": 1e9, "billion": 1e9,
}


def extract_money(text: str) -> list[float]:
    out = []
    for raw, unit in _MONEY.findall(text):
        unit = unit.lower() if unit else None
        out.append(float(raw.replace(",", "")) * _SCALE[unit])
    return out


def extract_percents(text: str) -> list[float]:
    return [float(raw.replace(",", "")) for raw in _PERCENT.findall(text)]


def expected_values(fixture: dict) -> dict[str, float]:
    workflow = fixture["workflow"]
    exp: dict[str, float] = {}
    for role, payload in workflow["exposure"].items():
        for metric, value in payload["terminal"].items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                exp[f"{role}.terminal.{metric}"] = float(value)
    base = exp.get("baseline.terminal.pfe_975")
    aug = exp.get("augmented.terminal.pfe_975")
    if base and aug is not None:
        exp["pfe_delta_pct"] = (aug - base) / base * 100.0
    w_stress = workflow.get("run_spec", {}).get("w_stress")
    if isinstance(w_stress, (int, float)):
        exp["w_stress"] = float(w_stress)
        exp["w_stress_pct"] = float(w_stress) * 100.0
    return exp


def _matches(claim: float, value: float, tol: float) -> bool:
    return abs(claim - value) <= tol * max(abs(value), 1e-12)


def match_claims(claims: list[float], expected: dict[str, float], *, kind: str) -> list[dict]:
    violations = []
    values = list(expected.values())
    for claim in claims:
        if any(_matches(claim, v, REL_TOL) for v in values):
            continue
        near = [k for k, v in expected.items() if _matches(claim, v, WRONG_VALUE_BAND)]
        if near:
            violations.append({
                "type": "wrong_value",
                "detail": f"{kind} claim {claim} near {near} but outside {REL_TOL:.1%} tolerance",
            })
        else:
            violations.append({
                "type": "invented_value",
                "detail": f"{kind} claim {claim} matches no expected value",
            })
    return violations
