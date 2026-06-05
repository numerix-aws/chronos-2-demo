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
    for key in ("status", "baseline_pfe_975", "augmented_pfe_975",
                "delta_pct", "delta_usd", "as_of", "stress_window",
                "n_paths", "endpoint_name", "git_sha", "timestamp"):
        assert key in art, f"missing {key}"
