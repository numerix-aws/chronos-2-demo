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
