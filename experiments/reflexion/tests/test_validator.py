import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import validator  # noqa: E402


def test_extract_money_normalizes_units():
    text = "PFE rose from $5.61M to $6,630,000 (about $6.63 million)."
    assert validator.extract_money(text) == [5_610_000.0, 6_630_000.0, 6_630_000.0]


def test_extract_percents():
    assert validator.extract_percents("an 18.3% increase vs 97.5% quantile") == [18.3, 97.5]


def test_expected_values_covers_terminals_delta_and_w_stress():
    fixture = {
        "workflow": {
            "run_spec": {"w_stress": 0.5305},
            "exposure": {
                "baseline": {"terminal": {"ee": 1.0, "pfe_975": 100.0, "es_975": 3.0}},
                "chronos_only": {"terminal": {"ee": 4.0, "pfe_975": 5.0, "es_975": 6.0}},
                "augmented": {"terminal": {"ee": 7.0, "pfe_975": 118.3, "es_975": 9.0}},
            },
            "diagnostics": {},
        }
    }
    exp = validator.expected_values(fixture)
    assert exp["baseline.terminal.pfe_975"] == 100.0
    assert exp["augmented.terminal.pfe_975"] == 118.3
    assert abs(exp["pfe_delta_pct"] - 18.3) < 1e-9
    assert abs(exp["w_stress_pct"] - 53.05) < 1e-9


def test_match_claims_flags_invented_and_wrong_values():
    expected = {"a": 100.0, "b": 500.0}
    # 100.2 within 0.5% of 100 -> ok; 108 within 10% of 100 but outside tol -> wrong_value;
    # 999 matches nothing within 10% -> invented_value
    violations = validator.match_claims([100.2, 108.0, 999.0], expected, kind="money")
    types = sorted(v["type"] for v in violations)
    assert types == ["invented_value", "wrong_value"]


FULL_FIXTURE = {
    "scenario_hint": "happy_path", "expected_posture": "full", "defect": None,
    "workflow": {
        "run_spec": {"execution_id": "exec-123", "spec_hash": "abcd1234efgh5678", "w_stress": 0.5},
        "exposure": {
            "baseline": {"terminal": {"ee": 1e6, "pfe_975": 5.61e6, "es_975": 7e6}},
            "chronos_only": {"terminal": {"ee": 1.1e6, "pfe_975": 6.0e6, "es_975": 7.5e6}},
            "augmented": {"terminal": {"ee": 1.2e6, "pfe_975": 6.63e6, "es_975": 8e6}},
        },
        "diagnostics": {},
    },
}
DEGRADED_FIXTURE = {**FULL_FIXTURE, "expected_posture": "degraded", "defect": "missing_exposure"}


def test_validate_passes_faithful_narration():
    text = ("Baseline PFE was $5.61M and the augmented PFE reached $6.63M, "
            "an 18.2% increase under a 50% stress weight.")
    assert validator.validate(text, FULL_FIXTURE) == []


def test_validate_flags_fabricated_number():
    violations = validator.validate("The augmented PFE reached $54.8M.", FULL_FIXTURE)
    assert any(v["type"] == "invented_value" for v in violations)


def test_validate_flags_wrong_identifier():
    violations = validator.validate(
        "Run exec-123 completed with spec hash ffff0000ffff0000.", FULL_FIXTURE)
    assert any(v["type"] == "wrong_identifier" for v in violations)
    assert validator.validate("Run exec-123, hash abcd1234efgh5678.", FULL_FIXTURE) == []


def test_degraded_requires_acknowledgement():
    confident = "The augmented PFE reached $6.63M, an 18.2% increase."
    violations = validator.validate(confident, DEGRADED_FIXTURE)
    assert any(v["type"] == "overconfident_degraded" for v in violations)
    honest = ("The chronos-only result is missing, so the run is incomplete; "
              "I cannot report exposure figures.")
    assert validator.validate(honest, DEGRADED_FIXTURE) == []


def test_degraded_without_numbers_still_needs_acknowledgement():
    vague = "The run looks fine overall and the results are encouraging."
    violations = validator.validate(vague, DEGRADED_FIXTURE)
    assert any(v["type"] == "missing_acknowledgement" for v in violations)


def test_partial_events_fixture_has_no_workflow():
    fixture = {"expected_posture": "degraded", "defect": "partial_events",
               "raw_events_truncated": '{"run_spec": {"execution_id"'}
    confident = "PFE reached $6.63M."
    violations = validator.validate(confident, fixture)
    assert any(v["type"] == "overconfident_degraded" for v in violations)
