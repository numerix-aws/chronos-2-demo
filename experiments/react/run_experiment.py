"""Harness: roles × arms × scenarios × trials, oracle-scored (spec §7)."""
import argparse
import json
import pathlib

import agents
import scenarios
from oracles import clarify, drilldown, triage

RESULTS = pathlib.Path(__file__).resolve().parent / "results"


def _run_clarify(arm: str, name: str, model_id):
    fixture = scenarios.load_clarify(name)
    result = (agents.clarify_arm_a(fixture) if arm == "a"
              else agents.clarify_arm_b(fixture, model_id))
    return result, clarify.score(result.outcome, fixture)


def _run_triage(arm: str, name: str, model_id):
    bundle = scenarios.load_triage(name)
    result = (agents.triage_arm_a(bundle, model_id) if arm == "a"
              else agents.triage_arm_b(bundle, model_id))
    return result, triage.score(result.final_text, bundle)


def _run_drilldown(arm: str, item: dict, model_id):
    bundle, question = scenarios.load_drilldown(item)
    if arm == "a":
        result = agents.drilldown_arm_a(bundle, question, model_id)
        report = drilldown.score(result.final_text, bundle, trace=None)
    else:
        result = agents.drilldown_arm_b(bundle, question, model_id)
        report = drilldown.score(result.final_text, bundle,
                                 trace=result.trace)
    return result, report


ROLES = {
    "clarify": (scenarios.CLARIFY, _run_clarify, lambda s: s),
    "triage": (scenarios.TRIAGE, _run_triage, lambda s: s),
    "drilldown": (scenarios.DRILLDOWN, _run_drilldown, lambda s: s["id"]),
}


def _record(role, arm, scenario_id, trial, result, report, error):
    record = {"role": role, "arm": arm, "scenario": scenario_id,
              "trial": trial, "error": error}
    if error is not None:
        record.update({"passed": None, "tool_calls": 0, "latency_s": 0.0,
                       "input_tokens": None, "output_tokens": None})
        return record
    record.update({
        "passed": report["passed"],
        "report": report,
        "final_text": result.final_text,
        "outcome": result.outcome,
        "tool_calls": len(result.trace.calls),
        "trace": result.trace.calls,
        "latency_s": result.latency_s,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
    })
    return record


def summarize(records: list[dict]) -> dict:
    summary: dict = {}
    for record in records:
        cell = summary.setdefault(record["role"], {}).setdefault(
            record["arm"],
            {"trials": 0, "errors": 0, "_passed": [], "_tools": [],
             "_tokens": [], "_latency": []})
        cell["trials"] += 1
        if record["error"] is not None:
            cell["errors"] += 1
            continue
        cell["_passed"].append(bool(record["passed"]))
        cell["_tools"].append(record["tool_calls"])
        if record["output_tokens"] is not None:
            cell["_tokens"].append(record["output_tokens"])
        cell["_latency"].append(record["latency_s"])
    for arms in summary.values():
        for cell in arms.values():
            scored = cell.pop("_passed")
            tools_used = cell.pop("_tools")
            tokens = cell.pop("_tokens")
            latency = cell.pop("_latency")
            cell["pass_rate"] = (sum(scored) / len(scored)) if scored else None
            cell["mean_tool_calls"] = (sum(tools_used) / len(tools_used)
                                       if tools_used else None)
            cell["mean_output_tokens"] = (sum(tokens) / len(tokens)
                                          if tokens else None)
            cell["mean_latency_s"] = (sum(latency) / len(latency)
                                      if latency else None)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--roles", default="clarify,triage,drilldown")
    parser.add_argument("--arms", default="a,b")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()
    RESULTS.mkdir(exist_ok=True)

    records = []
    for role in args.roles.split(","):
        scenario_list, runner, scenario_id = ROLES[role]
        for scenario in scenario_list:
            for arm in args.arms.split(","):
                for trial in range(1, args.trials + 1):
                    sid = scenario_id(scenario)
                    error, result, report = None, None, None
                    try:
                        result, report = runner(arm, scenario, args.model)
                    except Exception as exc:  # record loudly, keep going
                        error = f"{type(exc).__name__}: {exc}"
                        print(f"TRIAL FAILED {role}/{arm}/{sid}/t{trial}: "
                              f"{error}")
                    record = _record(role, arm, sid, trial, result, report,
                                     error)
                    records.append(record)
                    out = RESULTS / f"{role}_{arm}_{sid}_t{trial}.json"
                    out.write_text(json.dumps(record, indent=2,
                                              default=str) + "\n")
                    status = ("ERROR" if error else
                              "PASS" if record["passed"] else "FAIL")
                    print(f"{role:9s} {arm} {sid:22s} t{trial} {status}")

    summary = summarize(records)
    (RESULTS / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(f"\n{'role':9s} {'arm':3s} {'pass':>6s} {'tools':>6s} "
          f"{'tokens':>8s} {'lat(s)':>7s} {'err':>4s}")
    for role, arms in summary.items():
        for arm, cell in sorted(arms.items()):
            rate = (f"{cell['pass_rate']:.0%}"
                    if cell["pass_rate"] is not None else "n/a")
            print(f"{role:9s} {arm:3s} {rate:>6s} "
                  f"{cell['mean_tool_calls'] or 0:>6.1f} "
                  f"{cell['mean_output_tokens'] or 0:>8.0f} "
                  f"{cell['mean_latency_s'] or 0:>7.1f} "
                  f"{cell['errors']:>4d}")


if __name__ == "__main__":
    main()
