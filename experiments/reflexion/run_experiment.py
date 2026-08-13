"""Experiment harness: arms x scenarios x trials, oracle-scored (spec §6)."""
import argparse
import json
import pathlib
import time
from collections import defaultdict

import critic as critic_mod
import generator
import scenarios as scenarios_mod
import validator
from loop import run_reflexion

HERE = pathlib.Path(__file__).resolve().parent


def _load_fixture(name: str) -> dict:
    with open(HERE / "fixtures" / name, encoding="utf-8") as fh:
        return json.load(fh)


def run_trial(arm: str, scenario: dict, max_iters: int) -> dict:
    fixture = _load_fixture(scenario["fixture_file"])
    if arm == "A":
        generation = generator.generate(scenario["prompt"], fixture)
        narration = generation.text
        iterations, converged = 1, True
        latency = generation.latency_s
        input_tokens, output_tokens = generation.input_tokens, generation.output_tokens
        critic_passed = None  # Arm A never consults the critic
    else:
        result = run_reflexion(
            generate_fn=lambda fb: generator.generate(scenario["prompt"], fixture, feedback=fb),
            validate_fn=lambda text: validator.validate(text, fixture),
            critique_fn=lambda text: critic_mod.critique(text, fixture),
            max_iters=max_iters,
        )
        narration = result.final
        iterations, converged = result.iterations, result.converged
        latency = sum(a.latency_s for a in result.attempts)
        input_tokens = sum(a.input_tokens or 0 for a in result.attempts)
        output_tokens = sum(a.output_tokens or 0 for a in result.attempts)
        critic_passed = result.attempts[-1].critic_verdict.passed
    # Impartial final score: every narration in BOTH arms gets oracle-scored,
    # plus (for critic P/R) a fresh critic verdict on Arm A finals.
    oracle_violations = validator.validate(narration, fixture)
    if critic_passed is None:
        critic_passed = critic_mod.critique(narration, fixture).passed
    return {
        "arm": arm, "scenario": scenario["name"], "narration": narration,
        "oracle_violations": oracle_violations, "critic_passed": critic_passed,
        "iterations": iterations, "converged": converged, "latency_s": latency,
        "input_tokens": input_tokens, "output_tokens": output_tokens,
    }


def summarize(trials: list[dict]) -> dict:
    summary = {}
    by_arm = defaultdict(list)
    for trial in trials:
        by_arm[trial["arm"]].append(trial)
    for arm, rows in sorted(by_arm.items()):
        total = len(rows)
        flagged_oracle = [bool(r["oracle_violations"]) for r in rows]
        flagged_critic = [not r["critic_passed"] for r in rows]
        true_pos = sum(c and o for c, o in zip(flagged_critic, flagged_oracle))
        critic_flags = sum(flagged_critic)
        oracle_flags = sum(flagged_oracle)
        summary[arm] = {
            "trials": total,
            "oracle_violation_rate": oracle_flags / total,
            "violation_types": _type_counts(rows),
            "critic_precision": true_pos / critic_flags if critic_flags else None,
            "critic_recall": true_pos / oracle_flags if oracle_flags else None,
            "mean_iterations": sum(r["iterations"] for r in rows) / total,
            "mean_latency_s": sum(r["latency_s"] for r in rows) / total,
            "total_tokens": sum((r["input_tokens"] or 0) + (r["output_tokens"] or 0)
                                for r in rows),
        }
    return summary


def _type_counts(rows: list[dict]) -> dict:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        for violation in row["oracle_violations"]:
            counts[violation["type"]] += 1
    return dict(counts)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--arms", default="A,B")
    parser.add_argument("--scenarios", default="")  # comma list; empty = all
    parser.add_argument("--max-iters", type=int, default=3)
    args = parser.parse_args()
    wanted = set(filter(None, args.scenarios.split(",")))
    matrix = [s for s in scenarios_mod.SCENARIOS if not wanted or s["name"] in wanted]
    trials = []
    for scenario in matrix:
        for arm in args.arms.split(","):
            for trial_index in range(args.trials):
                print(f"[{scenario['name']}] arm={arm} trial={trial_index + 1}/{args.trials}")
                try:
                    trials.append(run_trial(arm, scenario, args.max_iters))
                except Exception as exc:  # record and continue; experiment, not prod
                    trials.append({"arm": arm, "scenario": scenario["name"],
                                   "error": f"{type(exc).__name__}: {exc}",
                                   "oracle_violations": [], "critic_passed": True,
                                   "iterations": 0, "converged": False,
                                   "latency_s": 0.0, "input_tokens": 0, "output_tokens": 0})
                    print(f"  FAILED: {exc}")
    ok_trials = [t for t in trials if "error" not in t]
    output = {"summary": summarize(ok_trials), "failed_trials":
              [t for t in trials if "error" in t], "trials": trials}
    out_path = HERE / "results" / f"experiment_{int(time.time())}.json"
    out_path.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
    print(json.dumps(output["summary"], indent=2))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
