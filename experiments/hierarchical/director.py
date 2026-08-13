"""Demo Director: coded control plane. No LLM in this module."""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class DirectorState:
    execution_id: str | None = None
    spec_hash: str | None = None
    run_status: str = "none"          # none | complete | failed
    bundle: dict | None = None        # react evidence bundle
    fixture: dict | None = None       # reflexion-shaped narration fixture
    critic_verdict: str | None = None  # pass | degraded | template
    diagnostics_ok: bool = False

    def summary(self) -> str:
        if self.run_status == "none":
            return "active run: none"
        return (f"active run: {self.run_status} (exec {self.execution_id}, "
                f"spec_hash {self.spec_hash}, diagnostics_ok={self.diagnostics_ok})")


# The spec §2 table. Routing authority lives HERE, not in any prompt.
_ROUTE_TABLE = {
    ("quant_run", "none"): "clarifier",
    ("quant_run", "complete"): "clarifier",
    ("quant_run", "failed"): "clarifier",
    ("what_if", "none"): "clarifier",
    ("what_if", "complete"): "clarifier",
    ("what_if", "failed"): "clarifier",
    ("followup_qa", "none"): "refuse",
    ("followup_qa", "complete"): "qa",
    ("followup_qa", "failed"): "refuse",
    ("failure_help", "none"): "refuse",
    ("failure_help", "complete"): "qa",
    ("failure_help", "failed"): "triage",
    ("out_of_scope", "none"): "direct",
    ("out_of_scope", "complete"): "direct",
    ("out_of_scope", "failed"): "direct",
    ("general_chat", "none"): "direct",
    ("general_chat", "complete"): "direct",
    ("general_chat", "failed"): "direct",
}


def route(intent: str, state: DirectorState) -> str:
    return _ROUTE_TABLE[(intent, state.run_status)]


def apply_outcome(state: DirectorState, bundle: dict,
                  fixture: dict | None, outcome: str) -> DirectorState:
    spec = bundle["run_spec"]
    return replace(
        state,
        execution_id=spec.get("execution_id"),
        spec_hash=spec.get("spec_hash"),
        run_status=outcome,
        bundle=bundle,
        fixture=fixture if outcome == "complete" else None,
        critic_verdict=None,
        diagnostics_ok=outcome == "complete"
        and "factor_coverage" in bundle.get("diagnostics", {}),
    )
