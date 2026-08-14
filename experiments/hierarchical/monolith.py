"""Arm A: one agent, every duty, every tool, stuffed context. No hierarchy."""
import json

import bridge
import specialists

MONOLITH_SYSTEM = (
    "You are the single assistant for a PFE/XVA demo. Depending on the "
    "user's message you must: clarify and compile run specs (use "
    "get_approved_defaults / ask_user / compile_spec); narrate completed "
    "run results faithfully with caveats where diagnostics are limited; "
    "answer technical follow-ups from the run artifacts; triage failed "
    "runs from the evidence; refuse questions no completed run can answer; "
    "and politely redirect out-of-scope requests. Never invent numbers, "
    "never claim to re-run or mutate anything. Chronos-2 augments, never "
    "replaces, the Monte Carlo engine."
)


def build_turn_prompt(transcript: list, bundle: dict | None, user_text: str) -> str:
    lines = [f"{t['role']}: {t['text']}" for t in transcript]
    convo = "\n".join(lines) if lines else "(session start)"
    if bundle is not None:
        evidence = ("Current run bundle (authoritative):\n"
                    + json.dumps(bundle, sort_keys=True, allow_nan=False))
    else:
        evidence = "There is no completed run in this session yet."
    return (f"Conversation so far:\n{convo}\n\n{evidence}\n\n"
            f"User message:\n---\n{user_text}\n---")


def tool_names(agent) -> list[str]:
    return list(agent.tool_names)


def make_monolith_agent(clarify_fixture: dict, bundle: dict | None, trace,
                        model_id: str | None = None, respond=None):
    sim = bridge.react_sim_user.SimUser(clarify_fixture, model_id=model_id,
                                        respond=respond)
    clarify, state = bridge.react_clarify_tools.make_clarify_tools(sim, trace)
    tools = list(clarify)
    if bundle is not None:
        tools += bridge.react_tools.make_evidence_tools(bundle, trace)
    return specialists._agent(MONOLITH_SYSTEM, tools, model_id), state, sim
