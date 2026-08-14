"""Read-only evidence tools over a bundle (spec §3/§8). No writes exist."""
import copy

_SUMMARY_KEYS = ("seq", "type", "name", "status", "ready", "task_status",
                 "scenario_role", "plot_role", "attempt", "message")


def make_evidence_functions(bundle: dict, trace) -> dict:
    def _return(name: str, args: dict, value):
        result = copy.deepcopy(value)
        trace.record(name, args, result)
        return result

    def list_events() -> list[dict]:
        """List the run's event stream as summaries (seq, name, status, ...).

        Use get_event(seq) for the full payload of one event."""
        return _return("list_events", {}, [
            {k: e[k] for k in _SUMMARY_KEYS if k in e}
            for e in bundle["events"]
        ])

    def get_event(seq: int) -> dict:
        """Fetch the full payload of one event by its seq number."""
        for event in bundle["events"]:
            if event["seq"] == seq:
                return _return("get_event", {"seq": seq}, event)
        return _return("get_event", {"seq": seq},
                       {"error": f"no event with seq {seq}"})

    def get_run_spec() -> dict:
        """Fetch the run's canonical RunSpec (spec_hash, execution_id, params)."""
        return _return("get_run_spec", {}, bundle["run_spec"])

    def get_artifact_manifest() -> list[dict]:
        """List run artifacts: uri, sha256, kind, scenario_role."""
        return _return("get_artifact_manifest", {}, bundle["artifact_manifest"])

    def get_task_status() -> dict:
        """Fetch the final Fargate engine task statuses (baseline_mc, chronos2)."""
        return _return("get_task_status", {}, bundle["task_status"])

    def get_diagnostics() -> dict | None:
        """Fetch blend diagnostics (attribution, coverage); null if unavailable."""
        return _return("get_diagnostics", {}, bundle["diagnostics"])

    return {fn.__name__: fn for fn in (
        list_events, get_event, get_run_spec, get_artifact_manifest,
        get_task_status, get_diagnostics,
    )}


def make_evidence_tools(bundle: dict, trace) -> list:
    from strands import tool

    return [tool(fn) for fn in make_evidence_functions(bundle, trace).values()]
