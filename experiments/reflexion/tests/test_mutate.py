import copy
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import mutate  # noqa: E402

FIXTURE = {
    "scenario_hint": "happy_path", "expected_posture": "full", "defect": None,
    "workflow": {
        "run_spec": {"execution_id": "e1", "spec_hash": "a" * 16},
        "exposure": {
            "baseline": {"spec_hash": "a" * 16, "terminal": {"pfe_975": 1.0}},
            "chronos_only": {"spec_hash": "a" * 16, "terminal": {"pfe_975": 2.0}},
            "augmented": {"spec_hash": "a" * 16, "terminal": {"pfe_975": 3.0}},
        },
        "diagnostics": {"spec_hash": "a" * 16},
    },
}


def test_missing_exposure_drops_chronos_only_and_marks_degraded():
    out = mutate.missing_exposure(copy.deepcopy(FIXTURE))
    assert "chronos_only" not in out["workflow"]["exposure"]
    assert out["expected_posture"] == "degraded"
    assert out["defect"] == "missing_exposure"
    assert "chronos_only" in FIXTURE["workflow"]["exposure"]  # input untouched


def test_id_mismatch_corrupts_augmented_spec_hash_only():
    out = mutate.id_mismatch(copy.deepcopy(FIXTURE))
    assert out["workflow"]["exposure"]["augmented"]["spec_hash"] != "a" * 16
    assert out["workflow"]["exposure"]["baseline"]["spec_hash"] == "a" * 16
    assert out["defect"] == "id_mismatch"


def test_partial_events_replaces_workflow_with_truncated_json():
    out = mutate.partial_events(copy.deepcopy(FIXTURE))
    assert "workflow" not in out
    raw = out["raw_events_truncated"]
    full = json.dumps(FIXTURE["workflow"], sort_keys=True, allow_nan=False)
    assert raw == full[: int(len(full) * 0.8)]
    try:
        json.loads(raw)
        raise AssertionError("truncated payload unexpectedly parseable")
    except json.JSONDecodeError:
        pass
    assert out["defect"] == "partial_events"
