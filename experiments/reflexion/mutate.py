"""Deterministic degradations of the happy-path fixture (spec §4)."""
import argparse
import copy
import json


def _degraded(fixture: dict, defect: str) -> dict:
    out = copy.deepcopy(fixture)
    out["expected_posture"] = "degraded"
    out["defect"] = defect
    out["scenario_hint"] = defect
    return out


def missing_exposure(fixture: dict) -> dict:
    out = _degraded(fixture, "missing_exposure")
    del out["workflow"]["exposure"]["chronos_only"]
    return out


def id_mismatch(fixture: dict) -> dict:
    out = _degraded(fixture, "id_mismatch")
    augmented = out["workflow"]["exposure"]["augmented"]
    augmented["spec_hash"] = "deadbeef" + augmented["spec_hash"][8:]
    return out


def partial_events(fixture: dict) -> dict:
    out = _degraded(fixture, "partial_events")
    raw = json.dumps(out.pop("workflow"), sort_keys=True, allow_nan=False)
    out["raw_events_truncated"] = raw[: int(len(raw) * 0.8)]
    return out


MUTATIONS = {
    "missing_exposure": missing_exposure,
    "id_mismatch": id_mismatch,
    "partial_events": partial_events,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="fixtures/happy_path.json")
    args = parser.parse_args()
    with open(args.source, encoding="utf-8") as fh:
        base = json.load(fh)
    for name, fn in MUTATIONS.items():
        path = f"fixtures/{name}.json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(fn(base), fh, sort_keys=True, indent=2, allow_nan=False)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
