"""Experiment harness: arms x scenarios x trials, oracle-scored (spec §6)."""
import argparse
import json
import os
import pathlib
import time
from collections import defaultdict

import critic as critic_mod
import generator
import scenarios as scenarios_mod
import validator
from loop import run_reflexion

HERE = pathlib.Path(__file__).resolve().parent


def load_checkpoint(path: pathlib.Path) -> list[dict]:
    """Load checkpoint trials; returns [] when missing/empty; skips corrupt trailing line."""
    if not path.exists():
        return []
    trials = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                trials.append(json.loads(line))
            except json.JSONDecodeError:
                # Skip corrupt trailing partial line (e.g., write interrupted mid-line)
                continue
    return trials


def append_checkpoint(path: pathlib.Path, trial: dict) -> None:
    """Append one trial as JSON line to checkpoint file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(trial, default=str) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def completed_per_cell(trials: list[dict]) -> dict[tuple[str, str], int]:
    """Count completed trials per (scenario, arm) — includes error rows."""
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for trial in trials:
        counts[(trial["scenario"], trial["arm"])] += 1
    return dict(counts)


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
    parser.add_argument("--checkpoint", type=pathlib.Path,
                        default=HERE / "results" / "checkpoint.jsonl")
    parser.add_argument("--fresh", action="store_true",
                        help="ignore and delete existing checkpoint")
    args = parser.parse_args()
    wanted = set(filter(None, args.scenarios.split(",")))
    matrix = [s for s in scenarios_mod.SCENARIOS if not wanted or s["name"] in wanted]

    # Load prior trials from checkpoint if resuming
    if args.fresh and args.checkpoint.exists():
        args.checkpoint.unlink()
    trials = load_checkpoint(args.checkpoint)
    completed = completed_per_cell(trials)

    for scenario in matrix:
        for arm in args.arms.split(","):
            cell_key = (scenario["name"], arm)
            done_count = completed.get(cell_key, 0)
            if done_count >= args.trials:
                continue  # All trials for this cell already done
            remaining = args.trials - done_count
            if done_count > 0:
                print(f"[{scenario['name']}] arm={arm} resuming: "
                      f"{done_count} done, {remaining} to go")
            for trial_index in range(remaining):
                print(f"[{scenario['name']}] arm={arm} trial={done_count + trial_index + 1}"
                      f"/{args.trials}")
                try:
                    trial = run_trial(arm, scenario, args.max_iters)
                except Exception as exc:  # record and continue; experiment, not prod
                    trial = {"arm": arm, "scenario": scenario["name"],
                             "error": f"{type(exc).__name__}: {exc}",
                             "oracle_violations": [], "critic_passed": True,
                             "iterations": 0, "converged": False,
                             "latency_s": 0.0, "input_tokens": 0, "output_tokens": 0}
                    print(f"  FAILED: {exc}")
                trials.append(trial)
                append_checkpoint(args.checkpoint, trial)

    ok_trials = [t for t in trials if "error" not in t]
    output = {"summary": summarize(ok_trials), "failed_trials":
              [t for t in trials if "error" in t], "trials": trials}
    out_path = HERE / "results" / f"experiment_{int(time.time())}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
    print(json.dumps(output["summary"], indent=2))
    print(f"wrote {out_path}")

    # Checkpoint absorbed into final results; delete it
    if args.checkpoint.exists():
        args.checkpoint.unlink()


if __name__ == "__main__":
    main()
