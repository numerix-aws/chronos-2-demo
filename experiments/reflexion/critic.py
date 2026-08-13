"""Layer-2 LLM critic: semantic faithfulness verdict (spec §2 items 1, 3, 4)."""
import json
import os
from typing import Literal

from pydantic import BaseModel

DEFAULT_MODEL_ID = os.environ.get("REFLEXION_MODEL_ID", "us.anthropic.claude-opus-5")

CRITIC_SYSTEM = """You are a quantitative-finance reviewer for a Numerix demo.
Judge whether a narration faithfully explains a Chronos-2 exposure run, using ONLY
the structured run artifacts provided. Deterministic checkers already verify exact
numbers, hashes, and IDs — do NOT re-verify arithmetic. You check semantics:

1. numerical_overclaim: directional or comparative claims the artifacts do not
   support (e.g. "Chronos-2 improved PFE" when augmented PFE is not better, or
   praising coverage the diagnostics do not show).
2. narrative_violation: the project story is "Chronos-2 AUGMENTS, never replaces,
   the parametric Monte Carlo engine". Flag any implication that Chronos-2 is the
   pricing engine, replaces the exposure machinery, or sees the same inputs as the
   baseline (only Chronos-2 sees the VIX/MOVE/WTI covariates — that asymmetry is
   deliberate).
3. missing_caveat: degraded/incomplete runs explained without caveats, or
   diagnostics limitations overstated (V1 diagnostics defend the headline only,
   not a full model-risk validation package).
4. ungrounded_claim: hand-waving that should cite coverage, tail dependence,
   w_stress, or provenance but cites nothing.

Pass the narration unless you find a concrete violation. Be specific: quote the
offending claim and the artifact evidence."""


class CriticViolation(BaseModel):
    type: Literal[
        "numerical_overclaim", "narrative_violation", "missing_caveat", "ungrounded_claim"
    ]
    claim: str
    evidence: str


class CriticVerdict(BaseModel):
    passed: bool
    violations: list[CriticViolation]


def build_critic_prompt(narration: str, fixture: dict) -> str:
    artifacts = json.dumps(
        fixture.get("workflow", {"raw_events_truncated": fixture.get("raw_events_truncated")}),
        sort_keys=True, allow_nan=False,
    )
    return (
        f"Run artifacts (ground truth):\n{artifacts}\n\n"
        f"Run posture: {fixture.get('expected_posture')}, defect: {fixture.get('defect')}.\n"
        "Remember: Chronos-2 augments, never replaces, the Monte Carlo engine.\n\n"
        f"Narration under review:\n---\n{narration}\n---\n\n"
        "Return your verdict."
    )


def critique(narration: str, fixture: dict, model_id: str | None = None) -> CriticVerdict:
    from strands import Agent
    from strands.models import BedrockModel

    agent = Agent(
        model=BedrockModel(model_id=model_id or DEFAULT_MODEL_ID),
        system_prompt=CRITIC_SYSTEM,
        tools=[],
        callback_handler=None,
    )
    return agent.structured_output(CriticVerdict, build_critic_prompt(narration, fixture))
