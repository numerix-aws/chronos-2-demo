"""Deterministic bundle-level degradations for the triage role (spec §5)."""
import argparse
import copy
import json
import pathlib

import bundle as bundle_mod

GROUND_TRUTH = {
    "missing_exposure": {
        "failed_step": "price_book",
        "keywords": ["missing", "chronos_only", "chronos-only", "absent",
                     "no exposure", "two of three", "incomplete"],
    },
    "id_mismatch": {
        "failed_step": "price_book",
        "keywords": ["spec_hash", "mismatch", "inconsistent", "provenance",
                     "deadbeef", "augmented"],
    },
    "partial_events": {
        "failed_step": "blend_paths",
        "keywords": ["truncated", "malformed", "incomplete", "unparseable",
                     "partial", "cut off", "blend"],
    },
    "poll_timeout": {
        "failed_step": "check_chronos2",
        "keywords": ["timeout", "timed out", "poll", "still running",
                     "running", "exhausted", "chronos"],
    },
    "hash_mismatch": {
        "failed_step": "artifact_integrity",
        "keywords": ["sha256", "hash", "mismatch", "integrity", "manifest",
                     "augmented", "disagree"],
    },
}


def _degraded(source: dict, defect: str) -> dict:
    out = copy.deepcopy(source)
    out["expected_posture"] = "degraded"
    out["defect"] = defect
    out["ground_truth"] = {"defect": defect, **GROUND_TRUTH[defect]}
    return out


def missing_exposure(source: dict) -> dict:
    out = _degraded(source, "missing_exposure")
    del out["exposure"]["chronos_only"]
    out["events"] = [e for e in out["events"]
                     if e.get("scenario_role") != "chronos_only"]
    for seq, event in enumerate(out["events"]):
        event["seq"] = seq
    out["artifact_manifest"] = [m for m in out["artifact_manifest"]
                                if m["scenario_role"] != "chronos_only"]
    return out


def id_mismatch(source: dict) -> dict:
    out = _degraded(source, "id_mismatch")
    augmented = out["exposure"]["augmented"]
    augmented["spec_hash"] = "deadbeef" + augmented["spec_hash"][8:]
    return out


def partial_events(source: dict) -> dict:
    out = _degraded(source, "partial_events")
    cut = next(i for i, e in enumerate(out["events"])
               if e["name"] == "blend_paths")
    dropped = out["events"][cut]
    raw = json.dumps(dropped, sort_keys=False)
    out["events"] = out["events"][:cut] + [{
        "seq": cut, "type": "malformed", "name": "malformed",
        "status": "unknown", "raw": raw[: len(raw) // 2],
    }]
    out["exposure"] = {}
    out["diagnostics"] = None
    out["artifact_manifest"] = [m for m in out["artifact_manifest"]
                                if m["kind"] == "paths"]
    return out


def poll_timeout(source: dict) -> dict:
    out = _degraded(source, "poll_timeout")
    out["task_status"]["chronos2"] = "RUNNING"
    out["exposure"] = {}
    out["diagnostics"] = None
    out["artifact_manifest"] = [
        m for m in out["artifact_manifest"]
        if m["kind"] == "paths" and m["scenario_role"] == "baseline"
    ]
    kept = [e for e in out["events"] if e["name"] in
            ("load_data", "plot", "run_baseline_mc", "run_chronos2",
             "check_baseline_mc") and e.get("plot_role") != "pfe_overlay"]
    for attempt in range(3):
        kept.append({"seq": 0, "type": "tool", "name": "check_chronos2",
                     "status": "done", "ready": False,
                     "task_status": "RUNNING", "attempt": attempt + 1})
    kept.append({"seq": 0, "type": "tool", "name": "check_chronos2",
                 "status": "failed",
                 "message": "check_chronos2 failed: poll attempt limit "
                            "exhausted; latest task_status=RUNNING"})
    for seq, event in enumerate(kept):
        event["seq"] = seq
    out["events"] = kept
    return out


def hash_mismatch(source: dict) -> dict:
    out = _degraded(source, "hash_mismatch")
    entry = next(m for m in out["artifact_manifest"]
                 if m["kind"] == "metrics" and m["scenario_role"] == "augmented")
    entry["sha256"] = "deadbeef" + entry["sha256"][8:]
    return out


MUTATIONS = {
    "missing_exposure": missing_exposure,
    "id_mismatch": id_mismatch,
    "partial_events": partial_events,
    "poll_timeout": poll_timeout,
    "hash_mismatch": hash_mismatch,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="fixtures")
    args = parser.parse_args()
    source = json.loads(
        (bundle_mod.REFLEXION_FIXTURES / "happy_path.json").read_text()
    )
    base = bundle_mod.build_bundle(source)
    out_dir = pathlib.Path(args.out_dir)
    for name, fn in MUTATIONS.items():
        path = out_dir / f"triage_{name}.json"
        path.write_text(json.dumps(fn(base), sort_keys=True, indent=2,
                                   allow_nan=False) + "\n")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
