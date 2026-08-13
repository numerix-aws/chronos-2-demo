import json
import pathlib

import bundle

_REFLEXION_FIXTURES = (
    pathlib.Path(__file__).resolve().parents[2] / "reflexion" / "fixtures"
)


def _mini_fixture() -> dict:
    payload = lambda role, source: {
        "execution_id": "e" * 32, "spec_hash": "a" * 64,
        "scenario_role": role, "source": source,
        "metrics_uri": f"s3://b/runs/{'e'*32}/metrics/{role}.json",
        "paths_uri": f"s3://b/runs/{'e'*32}/paths/{role}.parquet",
        "paths_sha256": "b" * 64,
        "ee": [1.0], "pfe_975": [2.0], "es_975": [3.0], "dates": ["2023-09-19"],
        "terminal": {"date": "2023-09-19", "ee": 1.0, "pfe_975": 2.0, "es_975": 3.0},
    }
    return {
        "defect": None, "expected_posture": "full", "scenario_hint": "happy_path",
        "workflow": {
            "run_spec": {"execution_id": "e" * 32, "spec_hash": "a" * 64,
                         "as_of_date": "2022-09-30", "conditioning": None},
            "exposure": {
                "baseline": payload("baseline", "parametric"),
                "chronos_only": payload("chronos_only", "chronos2"),
                "augmented": payload("augmented", "blended"),
            },
            "diagnostics": {"execution_id": "e" * 32},
        },
    }


def test_build_bundle_shape():
    b = bundle.build_bundle(_mini_fixture())
    assert b["expected_posture"] == "full" and b["defect"] is None
    assert b["run_spec"]["as_of_date"] == "2022-09-30"
    assert set(b["exposure"]) == {"baseline", "chronos_only", "augmented"}
    assert b["diagnostics"] == {"execution_id": "e" * 32}
    assert b["task_status"] == {"baseline_mc": "STOPPED", "chronos2": "STOPPED"}


def test_synthesized_events_cover_canonical_dag_in_order():
    b = bundle.build_bundle(_mini_fixture())
    names = [(e["name"], e.get("scenario_role") or e.get("plot_role")) for e in b["events"]]
    assert names == [
        ("load_data", None), ("plot", "regime_ribbon"),
        ("run_baseline_mc", None), ("run_chronos2", None),
        ("check_baseline_mc", None), ("check_chronos2", None),
        ("blend_paths", None),
        ("price_book", "baseline"), ("price_book", "chronos_only"),
        ("price_book", "augmented"), ("plot", "pfe_overlay"),
    ]
    assert [e["seq"] for e in b["events"]] == list(range(11))
    assert all(e["status"] == "done" for e in b["events"])
    checks = [e for e in b["events"] if e["name"].startswith("check_")]
    assert all(e["ready"] is True and e["task_status"] == "STOPPED" for e in checks)


def test_metrics_sha_injected_and_mirrored_in_manifest():
    b = bundle.build_bundle(_mini_fixture())
    by_role = {m["scenario_role"]: m for m in b["artifact_manifest"] if m["kind"] == "metrics"}
    assert set(by_role) == {"baseline", "chronos_only", "augmented"}
    for role, entry in by_role.items():
        assert entry["sha256"] == b["exposure"][role]["metrics_sha256"]
        assert entry["uri"] == b["exposure"][role]["metrics_uri"]
    paths = [m for m in b["artifact_manifest"] if m["kind"] == "paths"]
    assert {m["scenario_role"] for m in paths} == {"baseline", "chronos_only", "augmented"}
    assert all(m["sha256"] == "b" * 64 for m in paths)


def test_sha_deterministic_and_input_not_mutated():
    fx = _mini_fixture()
    before = json.dumps(fx, sort_keys=True)
    b1, b2 = bundle.build_bundle(fx), bundle.build_bundle(fx)
    assert json.dumps(fx, sort_keys=True) == before
    assert (b1["exposure"]["baseline"]["metrics_sha256"]
            == b2["exposure"]["baseline"]["metrics_sha256"])


def test_real_reflexion_fixtures_bundle():
    for name in ("happy_path", "conditional_whatif"):
        fx = json.loads((_REFLEXION_FIXTURES / f"{name}.json").read_text())
        b = bundle.build_bundle(fx)
        assert len(b["events"]) == 11 and b["diagnostics"] is not None
