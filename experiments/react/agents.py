"""Arm implementations: A = current architecture, B = ReAct (spec §3)."""
import json
import os
import time
from dataclasses import dataclass

from chronos2_demo.run_spec import (
    Clarification,
    canonical_run_payload,
    compile_run_spec,
)

import clarify_tools
import tools as tools_mod
from sim_user import SimUser
from trace import Trace

DEFAULT_MODEL_ID = os.environ.get("REACT_MODEL_ID",
                                  "us.anthropic.claude-opus-5")
PUBLIC_KEYS = ("run_spec", "events", "artifact_manifest", "task_status",
               "exposure", "diagnostics")

CLARIFY_SYSTEM = """You are the intake assistant for the Chronos-2 exposure \
demo. Your only job is to turn the user's request into ONE compiled \
canonical RunSpec, or to correct a false premise.

Rules:
- Chronos-2 AUGMENTS the parametric Monte Carlo engine by reweighting \
paths; it never replaces it and is not a pricing engine. If the request \
assumes otherwise, say so plainly before anything else.
- Call get_approved_defaults first. Prefer approved defaults over questions.
- Call ask_user ONLY when the user clearly wants something the defaults \
cannot express and the request does not say (hard budget: 2 questions).
- Compile by calling compile_spec with one self-contained English sentence: \
include the words "stage-safe" to apply the approved defaults, plus every \
explicit override (as-of date, "N paths", "N% stress", conditioning clause).
- Stop once compile_spec returns compiled=true. Reply with one short \
confirmation sentence."""

TRIAGE_SYSTEM = """You are a READ-ONLY triage assistant for a failed or \
inconsistent quantitative run. Use the evidence tools to find the exact \
step where the run became invalid and what the defect is.

Rules:
- You are read-only: you cannot rerun, fix, or modify anything, and you \
must not claim to have done so.
- Never present exposure numbers from this run as results — the run is not \
trustworthy.
- Finish with: the failed step, the defect, the evidence you used, and \
bounded next steps a human operator could take."""

DRILLDOWN_SYSTEM = """You answer follow-up questions about a COMPLETED \
quantitative run using the evidence tools.

Rules:
- Fetch only the evidence you need; start from list_events and \
get_diagnostics.
- Every number you cite must come from a tool result in this conversation. \
Never estimate, recall, or extrapolate numbers.
- Chronos-2 augments the Monte Carlo engine via reweighting; keep the \
narrative consistent with that.
- Be concise and cite which artifact each number came from."""


@dataclass
class ArmResult:
    final_text: str
    trace: Trace
    latency_s: float
    input_tokens: int | None
    output_tokens: int | None
    outcome: dict | None = None


def public_view(bundle: dict) -> dict:
    return {key: bundle[key] for key in PUBLIC_KEYS}


def triage_prompt_a(bundle: dict) -> str:
    view = public_view(bundle)
    broken = [e for e in view["events"]
              if e.get("status") in ("failed", "unknown")]
    return (
        "A quantitative run failed or produced inconsistent artifacts. "
        f"Error events: {json.dumps(broken, sort_keys=True)}\n\n"
        "Full run payload: "
        f"{json.dumps(view, sort_keys=True, allow_nan=False)}\n\n"
        "Explain exactly what went wrong."
    )


def drilldown_prompt_a(bundle: dict, question: str) -> str:
    view = public_view(bundle)
    return (
        f"{question}\n\nThe deterministic quantitative workflow completed. "
        "Answer from these structured results without changing any value: "
        f"{json.dumps(view, sort_keys=True, allow_nan=False)}"
    )


def _make_agent(system_prompt: str, agent_tools: list,
                model_id: str | None):
    from strands import Agent
    from strands.models import BedrockModel

    # No temperature/top_p/top_k: removed on Opus 5 (400 if sent).
    return Agent(
        model=BedrockModel(model_id=model_id or DEFAULT_MODEL_ID,
                           max_tokens=8192),
        system_prompt=system_prompt,
        tools=agent_tools,
        callback_handler=None,
    )


def _usage(result) -> tuple[int | None, int | None]:
    try:
        usage = result.metrics.accumulated_usage
        return usage["inputTokens"], usage["outputTokens"]
    except (AttributeError, KeyError, TypeError):
        return None, None


def _run(agent, prompt: str, trace: Trace) -> ArmResult:
    started = time.monotonic()
    result = agent(prompt)
    latency = time.monotonic() - started
    input_tokens, output_tokens = _usage(result)
    return ArmResult(str(result), trace, latency, input_tokens,
                     output_tokens)


def clarify_arm_a(fixture: dict) -> ArmResult:
    compiled = compile_run_spec(fixture["prompt"],
                                provenance=clarify_tools.DUMMY_PROVENANCE)
    if isinstance(compiled, Clarification):
        text, payload = compiled.message, None
    else:
        payload = {**canonical_run_payload(compiled),
                   "spec_hash": compiled.spec_hash}
        text = "Compiled the run as requested."
    outcome = {"compiled": payload, "questions": [], "final_text": text}
    return ArmResult(text, Trace(), 0.0, None, None, outcome)


def clarify_arm_b(fixture: dict, model_id: str | None = None) -> ArmResult:
    trace = Trace()
    sim = SimUser(fixture, model_id=model_id)
    agent_tools, state = clarify_tools.make_clarify_tools(sim, trace)
    agent = _make_agent(CLARIFY_SYSTEM, agent_tools, model_id)
    result = _run(agent, fixture["prompt"], trace)
    result.outcome = {"compiled": state["compiled"],
                      "questions": list(state["questions"]),
                      "final_text": result.final_text}
    return result


def triage_arm_a(bundle: dict, model_id: str | None = None) -> ArmResult:
    agent = _make_agent(TRIAGE_SYSTEM, [], model_id)
    return _run(agent, triage_prompt_a(bundle), Trace())


def triage_arm_b(bundle: dict, model_id: str | None = None) -> ArmResult:
    trace = Trace()
    agent = _make_agent(
        TRIAGE_SYSTEM, tools_mod.make_evidence_tools(bundle, trace), model_id)
    return _run(agent, "A quantitative run failed or produced inconsistent "
                       "artifacts. Investigate with the evidence tools and "
                       "report.", trace)


def drilldown_arm_a(bundle: dict, question: str,
                    model_id: str | None = None) -> ArmResult:
    agent = _make_agent(DRILLDOWN_SYSTEM, [], model_id)
    return _run(agent, drilldown_prompt_a(bundle, question), Trace())


def drilldown_arm_b(bundle: dict, question: str,
                    model_id: str | None = None) -> ArmResult:
    trace = Trace()
    agent = _make_agent(
        DRILLDOWN_SYSTEM, tools_mod.make_evidence_tools(bundle, trace),
        model_id)
    return _run(agent, question, trace)
