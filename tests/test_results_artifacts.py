import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[1] / "docs" / "results"


def test_latency_artifact_has_required_shape():
    art = json.loads((RESULTS / "latency_benchmark.json").read_text())
    for key in ("closed_form_seconds", "nested_mc_seconds", "speedup_x",
                "nested_n_revaluations", "status"):
        assert key in art, f"missing {key}"
