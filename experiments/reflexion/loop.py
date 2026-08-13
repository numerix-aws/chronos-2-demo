"""Reflexion loop: generate -> oracle -> critic -> regenerate with feedback (spec §3)."""
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Attempt:
    narration: str
    oracle_violations: list
    critic_verdict: Any
    latency_s: float
    input_tokens: int | None
    output_tokens: int | None


@dataclass
class LoopResult:
    final: str
    iterations: int
    converged: bool
    attempts: list = field(default_factory=list)


def format_feedback(oracle_violations: list, critic_verdict: Any) -> str:
    lines = [
        f"- [{violation['type']}] {violation['detail']}" for violation in oracle_violations
    ]
    if not getattr(critic_verdict, "passed", True):
        for violation in getattr(critic_verdict, "violations", []):
            claim = getattr(violation, "claim", "")
            evidence = getattr(violation, "evidence", "")
            vtype = getattr(violation, "type", "critic_finding")
            lines.append(f"- [{vtype}] {claim} (evidence: {evidence})")
    return "\n".join(lines)


def run_reflexion(
    generate_fn: Callable[[str | None], Any],
    validate_fn: Callable[[str], list],
    critique_fn: Callable[[str], Any],
    max_iters: int = 3,
) -> LoopResult:
    feedback = None
    attempts: list[Attempt] = []
    for iteration in range(1, max_iters + 1):
        generation = generate_fn(feedback)
        narration = generation.text
        oracle_violations = validate_fn(narration)
        verdict = critique_fn(narration)
        attempts.append(Attempt(
            narration, oracle_violations, verdict,
            generation.latency_s, generation.input_tokens, generation.output_tokens,
        ))
        if not oracle_violations and getattr(verdict, "passed", False):
            return LoopResult(narration, iteration, True, attempts)
        feedback = format_feedback(oracle_violations, verdict)
    return LoopResult(narration, max_iters, False, attempts)
