"""Per-arm session loops. All LLM touchpoints go through Seams (injectable)."""
import time
from dataclasses import dataclass
from typing import Callable

import bridge
import director
import intents
import monolith
import sessions
import specialists


@dataclass
class Seams:
    classify: Callable
    clarify: Callable
    answer: Callable
    direct: Callable
    publish: Callable
    respond: Callable | None = None


def default_seams(model_id: str | None = None) -> Seams:
    def clarify(agent, cstate, user):
        agent(user)
        return cstate["compiled"]

    return Seams(
        classify=lambda user, summary: intents.classify(user, summary,
                                                        model_id=model_id),
        clarify=clarify,
        answer=lambda agent, prompt: str(agent(prompt)),
        direct=lambda user, summary, route: specialists.direct_reply(
            user, summary, route, model_id=model_id),
        publish=lambda user, fixture, state: director.publish_narration(
            user, fixture, state, model_id=model_id),
        respond=None,
    )


def render_run_failed_notice(state: director.DirectorState) -> str:
    return (f"The run did not complete (status: failed, exec "
            f"{state.execution_id}). No results are available; ask me to "
            "diagnose what went wrong.")


def _state_snapshot(state: director.DirectorState) -> dict:
    return {"run_status": state.run_status,
            "has_bundle": state.bundle is not None,
            "execution_id": state.execution_id,
            "spec_hash": state.spec_hash}


def run_director_session(session: dict, seams: Seams) -> dict:
    state = director.DirectorState()
    records, started = [], time.monotonic()
    for turn in session["turns"]:
        turn_started = time.monotonic()
        trace = bridge.react_trace.Trace()
        verdict = seams.classify(turn["user"], state.summary())
        route = director.route(verdict.intent, state)
        channel = None
        if route == "clarifier":
            fixture = session["clarify"] or specialists.default_clarify_fixture(
                turn["user"])
            agent, cstate = specialists.make_clarifier(
                fixture, trace, respond=seams.respond)
            compiled = seams.clarify(agent, cstate, turn["user"])
            if compiled is None:
                reply = str(cstate.get("final_text") or "Clarification needed.")
            else:
                bundle, nfix, outcome = sessions.resolve_outcome(
                    turn["resolves_to"])
                state = director.apply_outcome(state, bundle, nfix, outcome)
                if outcome == "complete":
                    pub = seams.publish(turn["user"], nfix, state)
                    reply, channel = pub.text, pub.channel
                else:
                    reply = render_run_failed_notice(state)
        elif route in ("qa", "triage"):
            agent = specialists.make_specialist(route, state.bundle, trace)
            reply = seams.answer(agent, turn["user"])
        else:  # direct | refuse — Director prose, no tools
            reply = seams.direct(turn["user"], state.summary(), route)
        records.append({
            "user": turn["user"], "intent": verdict.intent,
            "confidence": getattr(verdict, "confidence", None), "route": route,
            "reply": reply, "tool_calls": trace.tool_names(),
            "publication_channel": channel,
            "state_after": _state_snapshot(state),
            "latency_s": time.monotonic() - turn_started,
        })
    return {"session": session["session"], "arm": "director",
            "turns": records, "wall_clock_s": time.monotonic() - started}


def run_monolith_session(session: dict, seams: Seams) -> dict:
    bundle, transcript, run_status = None, [], "none"
    records, started = [], time.monotonic()
    for turn in session["turns"]:
        turn_started = time.monotonic()
        trace = bridge.react_trace.Trace()
        clarify_fixture = session["clarify"] or (
            specialists.default_clarify_fixture(turn["user"]))
        agent, cstate = monolith.make_monolith_agent(
            clarify_fixture, bundle, trace, respond=seams.respond)
        prompt = monolith.build_turn_prompt(transcript, bundle, turn["user"])
        reply = seams.answer(agent, prompt)
        if "resolves_to" in turn and cstate["compiled"] is None:
            # Give the seam a chance to report a compile the stuffed agent
            # made mid-answer (live: cstate already updated by the tool call;
            # smoke: the fake returns a compiled dict).
            cstate["compiled"] = seams.clarify(agent, cstate, turn["user"])
        if "resolves_to" in turn and cstate["compiled"] is not None:
            bundle, _, outcome = sessions.resolve_outcome(turn["resolves_to"])
            run_status = outcome
        records.append({
            "user": turn["user"], "intent": None, "confidence": None,
            "route": None, "reply": reply, "tool_calls": trace.tool_names(),
            "publication_channel": None,
            "state_after": {"run_status": run_status,
                            "has_bundle": bundle is not None,
                            "execution_id": (bundle or {}).get(
                                "run_spec", {}).get("execution_id"),
                            "spec_hash": (bundle or {}).get(
                                "run_spec", {}).get("spec_hash")},
            "latency_s": time.monotonic() - turn_started,
        })
        transcript += [{"role": "user", "text": turn["user"]},
                       {"role": "assistant", "text": reply}]
    return {"session": session["session"], "arm": "monolith",
            "turns": records, "wall_clock_s": time.monotonic() - started}
