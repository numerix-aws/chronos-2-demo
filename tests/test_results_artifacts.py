import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[1] / "docs" / "results"


def test_latency_artifact_has_required_shape():
    art = json.loads((RESULTS / "latency_benchmark.json").read_text())
    for key in ("closed_form_seconds", "nested_mc_seconds", "speedup_x",
                "nested_n_revaluations", "status"):
        assert key in art, f"missing {key}"


def test_headline_artifact_has_required_shape():
    art = json.loads((RESULTS / "headline_calibration.json").read_text())
    for key in ("run_spec", "inputs", "terminal_metrics", "diagnostics"):
        assert key in art, f"missing {key}"
    for key in ("as_of_date", "n_paths", "w_stress", "spec_hash", "provenance"):
        assert key in art["run_spec"], f"missing run_spec.{key}"
    for role in ("baseline", "chronos_only", "augmented"):
        assert "pfe_975" in art["terminal_metrics"][role], f"missing {role} pfe_975"


def test_5000_path_headline_artifact_has_required_shape():
    art = json.loads((RESULTS / "headline_calibration_5000paths.json").read_text())
    for key in ("status", "baseline_pfe_975", "augmented_pfe_975",
                "delta_pct", "delta_usd", "as_of", "stress_window",
                "n_paths", "endpoint_name", "git_sha", "timestamp"):
        assert key in art, f"missing {key}"
