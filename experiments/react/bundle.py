"""Convert reflexion narration fixtures into react evidence bundles (spec §5)."""
import argparse
import copy
import hashlib
import json
import pathlib

REFLEXION_FIXTURES = (
    pathlib.Path(__file__).resolve().parents[1] / "reflexion" / "fixtures"
)
ROLES = ("baseline", "chronos_only", "augmented")


def payload_sha256(payload: dict) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def synthesize_events(workflow: dict) -> list[dict]:
    events: list[dict] = []

    def add(name: str, **extra) -> None:
        events.append({"seq": len(events), "type": "tool", "name": name,
                       "status": "done", **extra})

    add("load_data")
    add("plot", plot_role="regime_ribbon")
    add("run_baseline_mc")
    add("run_chronos2")
    add("check_baseline_mc", ready=True, task_status="STOPPED")
    add("check_chronos2", ready=True, task_status="STOPPED")
    add("blend_paths")
    for role in ROLES:
        payload = workflow.get("exposure", {}).get(role)
        if payload is not None:
            add("price_book", scenario_role=role,
                source=payload.get("source"), terminal=payload.get("terminal"))
    add("plot", plot_role="pfe_overlay")
    return events


def build_bundle(fixture: dict) -> dict:
    workflow = copy.deepcopy(fixture["workflow"])
    manifest = []
    for role in ROLES:
        payload = workflow.get("exposure", {}).get(role)
        if payload is None:
            continue
        payload["metrics_sha256"] = payload_sha256(payload)
        manifest.append({"uri": payload["metrics_uri"],
                         "sha256": payload["metrics_sha256"],
                         "kind": "metrics", "scenario_role": role})
        manifest.append({"uri": payload["paths_uri"],
                         "sha256": payload["paths_sha256"],
                         "kind": "paths", "scenario_role": role})
    return {
        "defect": fixture.get("defect"),
        "expected_posture": fixture.get("expected_posture", "full"),
        "ground_truth": None,
        "run_spec": workflow["run_spec"],
        "events": synthesize_events(workflow),
        "artifact_manifest": manifest,
        "task_status": {"baseline_mc": "STOPPED", "chronos2": "STOPPED"},
        "exposure": workflow.get("exposure", {}),
        "diagnostics": workflow.get("diagnostics"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="fixtures")
    args = parser.parse_args()
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for source, target in (("happy_path", "drilldown_happy"),
                           ("conditional_whatif", "drilldown_conditional")):
        fixture = json.loads((REFLEXION_FIXTURES / f"{source}.json").read_text())
        path = out_dir / f"{target}.json"
        path.write_text(json.dumps(build_bundle(fixture), sort_keys=True,
                                   indent=2, allow_nan=False) + "\n")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
