"""Tool-scoped specialist constructors. Allowlists are physical: each agent
is built with only its route's tools — violations are impossible, not policed."""
import bridge

EVIDENCE_TOOL_NAMES = ("list_events", "get_event", "get_run_spec",
                       "get_artifact_manifest", "get_task_status",
                       "get_diagnostics")
CLARIFY_TOOL_NAMES = ("get_approved_defaults", "ask_user", "compile_spec")

ALLOWLISTS = {
    "clarifier": frozenset(CLARIFY_TOOL_NAMES),
    "qa": frozenset(EVIDENCE_TOOL_NAMES),
    "triage": frozenset(EVIDENCE_TOOL_NAMES),
    "direct": frozenset(),
    "refuse": frozenset(),
}

CLARIFIER_SYSTEM = (
    "You turn a user's request into a compiled canonical RunSpec for a "
    "PFE/XVA demo. Use get_approved_defaults for anything the user left "
    "open; ask_user at most twice, and only when a required field cannot "
    "come from the prompt or the defaults. Call compile_spec once you can. "
    "You never run the workflow yourself."
)

QA_SYSTEM = (
    "You answer technical follow-up questions about a completed quantitative "
    "run using ONLY the read-only evidence tools. Cite values you fetched; "
    "never invent numbers; never claim to re-run or change anything. "
    "Chronos-2 augments, never replaces, the Monte Carlo engine — correct "
    "any premise that says otherwise."
)

TRIAGE_SYSTEM = (
    "You diagnose a failed quantitative run using ONLY the read-only "
    "evidence tools. Name the exact step where the run became invalid and "
    "the defect. Make no quantitative claims from the broken run and do "
    "not claim to have re-run or fixed anything."
)

DIRECT_SYSTEM = (
    "You are the voice of a demo control plane. Reply in 1-3 sentences. "
    "You have no tools and must not invent capabilities or results."
)

_DIRECT_INSTRUCTIONS = {
    "direct": ("The request is out of scope for this demo (or small talk). "
               "Answer briefly and redirect to what the demo can do: run "
               "scenarios, explain results, diagnose failed runs."),
    "refuse": ("There is no completed run that can answer this. Say so "
               "plainly, state the session status, and offer the next step. "
               "Use no numeric claims — no numbers at all."),
}


def default_clarify_fixture(prompt: str) -> dict:
    return {"scenario": "inline", "prompt": prompt, "expected_posture": "compile",
            "hidden_intent": {}, "known_fields": [], "must_resolve": [],
            "max_questions_ok": 0}


def _agent(system_prompt: str, tools: list, model_id: str | None):
    from strands import Agent
    from strands.models import BedrockModel

    return Agent(
        model=BedrockModel(model_id=model_id or bridge.DEFAULT_MODEL_ID,
                           max_tokens=8192),
        system_prompt=system_prompt, tools=tools, callback_handler=None)


def make_clarifier(clarify_fixture: dict, trace, model_id: str | None = None,
                   respond=None):
    sim = bridge.react_sim_user.SimUser(clarify_fixture, model_id=model_id,
                                        respond=respond)
    tools, state = bridge.react_clarify_tools.make_clarify_tools(sim, trace)
    return _agent(CLARIFIER_SYSTEM, tools, model_id), state, sim


def make_specialist(route: str, bundle: dict, trace, model_id: str | None = None):
    system = {"qa": QA_SYSTEM, "triage": TRIAGE_SYSTEM}[route]
    tools = bridge.react_tools.make_evidence_tools(bundle, trace)
    return _agent(system, tools, model_id)


def build_direct_prompt(user_text: str, state_summary: str, route: str) -> str:
    return (f"Session state: {state_summary}\n{_DIRECT_INSTRUCTIONS[route]}\n\n"
            f"User message:\n---\n{user_text}\n---")


def direct_reply(user_text: str, state_summary: str, route: str,
                 model_id: str | None = None) -> str:
    agent = _agent(DIRECT_SYSTEM, [], model_id)
    return str(agent(build_direct_prompt(user_text, state_summary, route)))
