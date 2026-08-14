"""Harness: arms x sessions x trials, scored per turn, results to JSON."""
import argparse
import json
import pathlib
import time

import runner
import sessions
import specialists
from scoring import answers, boundary, routing, state as state_scoring


def _score_director_turn(turn, record):
    return {
        "routing": routing.score_turn(record["intent"], record["route"], turn),
        "state": state_scoring.score_state(
            _StateView(record["state_after"]), turn["expected_state_after"]),
        "answer": _answer_score(turn, record),
        "boundary": boundary.violations(
            [{"name": n} for n in record["tool_calls"]],
            specialists.ALLOWLISTS[turn["expected_route"]]),
    }


class _StateView:
    def __init__(self, snapshot):
        self.run_status = snapshot["run_status"]
        self.bundle = object() if snapshot["has_bundle"] else None


def _answer_score(turn, record):
    kind = turn["score"]["kind"]
    fixture = record.get("_fixture")
    bundle = record.get("_bundle")
    return answers.score(kind, record["reply"], fixture=fixture, bundle=bundle)


def _attach_evidence(session, records):
    """Give each record the active fixture/bundle its score kind needs."""
    fixture = bundle = None
    for turn, record in zip(session["turns"], records):
        if "resolves_to" in turn:
            b, f, _ = sessions.resolve_outcome(turn["resolves_to"])
            bundle, fixture = b, f
        record["_bundle"], record["_fixture"] = bundle, fixture


def _score_monolith_turn(turn, record):
    return {
        "routing": None, "state": None,
        "answer": _answer_score(turn, record),
        "boundary": boundary.violations(
            [{"name": n} for n in record["tool_calls"]],
            specialists.ALLOWLISTS[turn["expected_route"]]),
    }


def run_matrix(trials: int, seams_factory, out_dir, session_filter=None,
               model_id=None):
    out_dir = pathlib.Path(out_dir)
    all_sessions = [s for s in sessions.load_all()
                    if not session_filter or s["session"] in session_filter]
    results = []
    for arm, run_fn, scorer in (
            ("director", runner.run_director_session, _score_director_turn),
            ("monolith", runner.run_monolith_session, _score_monolith_turn)):
        for session in all_sessions:
            for trial in range(trials):
                seams = seams_factory(model_id)
                if arm == "monolith" and seams.respond is None:
                    # Live Arm A: report-only — the stuffed agent compiles (or
                    # not) via its own tool calls; never re-invoke it. Fake
                    # seams (respond set) keep their injected clarify.
                    seams.clarify = lambda agent, cstate, user: cstate["compiled"]
                result = run_fn(session, seams)
                _attach_evidence(session, result["turns"])
                for turn, record in zip(session["turns"], result["turns"]):
                    record["scores"] = scorer(turn, record)
                    record.pop("_bundle", None)
                    record.pop("_fixture", None)
                result["trial"] = trial
                results.append(result)
    summary = _summarize(results)
    out_path = out_dir / f"experiment_{int(time.time())}.json"
    out_path.write_text(json.dumps({"summary": summary, "results": results},
                                   indent=2, default=str))
    _print_table(summary)
    return summary


def _summarize(results: list) -> dict:
    by_arm = []
    for arm in ("director", "monolith"):
        rows = [t for r in results if r["arm"] == arm for t in r["turns"]]
        n = len(rows)
        routed = [t for t in rows if t["scores"]["routing"]]
        by_arm.append({
            "arm": arm, "turns": n,
            "intent_accuracy": (sum(t["scores"]["routing"]["intent_correct"]
                                    for t in routed) / len(routed)) if routed else None,
            "route_accuracy": (sum(t["scores"]["routing"]["route_correct"]
                                   for t in routed) / len(routed)) if routed else None,
            "state_accuracy": (sum(t["scores"]["state"]["passed"]
                                   for t in routed) / len(routed)) if routed else None,
            "boundary_violations": sum(len(t["scores"]["boundary"]) for t in rows),
            "answer_pass_rate": sum(t["scores"]["answer"]["passed"]
                                    for t in rows) / n if n else None,
            "publication_channels": _histogram(
                t["publication_channel"] for t in rows),
            "mean_latency_s": sum(t["latency_s"] for t in rows) / n if n else None,
        })
    return {"by_arm": by_arm}


def _histogram(values) -> dict:
    counts = {}
    for v in values:
        if v is not None:
            counts[v] = counts.get(v, 0) + 1
    return counts


def _print_table(summary: dict) -> None:
    cols = ("arm", "turns", "intent_accuracy", "route_accuracy",
            "state_accuracy", "boundary_violations", "answer_pass_rate",
            "publication_channels", "mean_latency_s")
    for row in summary["by_arm"]:
        print(" | ".join(f"{c}={row[c]}" for c in cols))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--sessions", nargs="*", default=None)
    parser.add_argument("--model-id", default=None)
    args = parser.parse_args()
    run_matrix(args.trials, runner_default_factory, "results",
               session_filter=args.sessions, model_id=args.model_id)


def runner_default_factory(model_id):
    return runner.default_seams(model_id)


if __name__ == "__main__":
    main()
