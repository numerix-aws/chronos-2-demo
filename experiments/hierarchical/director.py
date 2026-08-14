"""Demo Director: coded control plane. No LLM in this module."""
from dataclasses import dataclass, field, replace

import bridge


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


DEGRADED_INSTRUCTION = (
    "DEGRADED MODE: your previous answers failed validation. Write a "
    "caveat-first summary: state that the narration could not be validated "
    "against the run artifacts, acknowledge any defect, and make NO numeric "
    "claim that is not verbatim from the structured results. Prefer no "
    "numbers at all."
)


@dataclass
class Publication:
    text: str
    channel: str  # narrator | degraded | template
    iterations: int
    attempts: list = field(default_factory=list)


def render_failure_template(state: DirectorState, violations: list) -> str:
    kinds = ", ".join(sorted({v["type"] for v in violations})) or "unknown"
    return (
        f"Run {state.execution_id or 'unknown'} finished, but its narration "
        f"failed validation after retries ({len(violations)} unresolved "
        f"issue(s): {kinds}). The structured artifacts for spec_hash "
        f"{state.spec_hash or 'unknown'} are authoritative; please read the "
        "exposure and diagnostics values from the artifact bundle directly."
    )


def publish_narration(user_prompt: str, fixture: dict, state: DirectorState, *,
                      generate_fn=None, validate_fn=None, critique_fn=None,
                      model_id: str | None = None) -> Publication:
    generate_fn = generate_fn or (lambda feedback: bridge.reflexion_generator.generate(
        user_prompt, fixture, feedback, model_id=model_id))
    validate_fn = validate_fn or (
        lambda text: bridge.reflexion_validator.validate(text, fixture))
    critique_fn = critique_fn or (
        lambda text: bridge.reflexion_critic.critique(text, fixture, model_id=model_id))

    result = bridge.reflexion_loop.run_reflexion(
        generate_fn, validate_fn, critique_fn, max_iters=3)
    if result.converged:
        return Publication(result.final, "narrator", result.iterations, result.attempts)

    last = result.attempts[-1]
    feedback = bridge.reflexion_loop.format_feedback(
        last.oracle_violations, last.critic_verdict)
    degraded = generate_fn(f"{feedback}\n\n{DEGRADED_INSTRUCTION}")
    degraded_violations = validate_fn(degraded.text)
    if not degraded_violations:
        return Publication(degraded.text, "degraded",
                           result.iterations + 1, result.attempts)
    return Publication(render_failure_template(state, degraded_violations),
                       "template", result.iterations + 1, result.attempts)
