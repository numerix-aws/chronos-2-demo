import json

import bundle
import mutate
from tests.test_bundle import _mini_fixture


def _base() -> dict:
    return bundle.build_bundle(_mini_fixture())


def test_all_five_mutations_registered():
    assert set(mutate.MUTATIONS) == {
        "missing_exposure", "id_mismatch", "partial_events",
        "poll_timeout", "hash_mismatch",
    }


def test_every_mutation_sets_degraded_posture_and_ground_truth():
    for name, fn in mutate.MUTATIONS.items():
        out = fn(_base())
        assert out["expected_posture"] == "degraded" and out["defect"] == name
        gt = out["ground_truth"]
        assert gt["defect"] == name and gt["failed_step"] and gt["keywords"]


def test_missing_exposure_drops_chronos_only_everywhere():
    out = mutate.MUTATIONS["missing_exposure"](_base())
    assert "chronos_only" not in out["exposure"]
    assert not [e for e in out["events"]
                if e.get("scenario_role") == "chronos_only"]
    assert not [m for m in out["artifact_manifest"]
                if m["scenario_role"] == "chronos_only"]
    assert out["ground_truth"]["failed_step"] == "price_book"


def test_id_mismatch_corrupts_augmented_spec_hash_only():
    base = _base()
    original = base["exposure"]["augmented"]["spec_hash"]
    out = mutate.MUTATIONS["id_mismatch"](base)
    corrupted = out["exposure"]["augmented"]["spec_hash"]
    assert corrupted != original and corrupted.startswith("deadbeef")
    assert out["exposure"]["baseline"]["spec_hash"] == original
    assert out["run_spec"]["spec_hash"] == original


def test_partial_events_truncates_after_check_chronos2():
    out = mutate.MUTATIONS["partial_events"](_base())
    names = [e["name"] for e in out["events"]]
    assert names[-1] == "malformed" and "blend_paths" not in names
    assert out["events"][-1]["raw"].startswith('{"seq"')
    assert out["exposure"] == {} and out["diagnostics"] is None
    assert out["ground_truth"]["failed_step"] == "blend_paths"


def test_poll_timeout_leaves_chronos_running_with_no_downstream():
    out = mutate.MUTATIONS["poll_timeout"](_base())
    assert out["task_status"]["chronos2"] == "RUNNING"
    last = out["events"][-1]
    assert last["name"] == "check_chronos2" and last["status"] == "failed"
    assert "poll attempt limit exhausted" in last["message"]
    polls = [e for e in out["events"]
             if e["name"] == "check_chronos2" and e["status"] == "done"]
    assert len(polls) == 3 and all(e["ready"] is False for e in polls)
    assert set(out["exposure"]) == set()
    assert "blend_paths" not in [e["name"] for e in out["events"]]
    assert out["ground_truth"]["failed_step"] == "check_chronos2"


def test_hash_mismatch_diverges_manifest_from_exposure():
    out = mutate.MUTATIONS["hash_mismatch"](_base())
    entry = next(m for m in out["artifact_manifest"]
                 if m["kind"] == "metrics" and m["scenario_role"] == "augmented")
    assert entry["sha256"] != out["exposure"]["augmented"]["metrics_sha256"]
    assert entry["sha256"].startswith("deadbeef")


def test_mutations_do_not_share_state():
    base = _base()
    snapshot = json.dumps(base, sort_keys=True)
    for fn in mutate.MUTATIONS.values():
        fn(base)
    assert json.dumps(base, sort_keys=True) == snapshot
