"""Clarification-role tools: defaults, ask_user, compile_spec (spec §3)."""
from chronos2_demo.run_spec import (
    PROFILE,
    Clarification,
    canonical_run_payload,
    compile_run_spec,
)

# Keys mirror agent/runtime/agent.py PROVENANCE_ENV; identical values on every
# compile keep spec_hash comparable across arms and against the oracle.
DUMMY_PROVENANCE = {name: "experiment" for name in (
    "market_snapshot_id", "market_sha256", "covariate_snapshot_id",
    "covariate_sha256", "chronos_endpoint", "chronos_model_version",
    "baseline_image_digest", "chronos_image_digest", "agent_image_digest",
    "book_version", "blend_version", "pricing_version",
    "tool_bundle_version", "strands_version",
)}
MAX_QUESTIONS = 2


def make_clarify_functions(sim_user, trace) -> tuple[dict, dict]:
    state = {"questions": [], "compiled": None}

    def _return(name: str, args: dict, value):
        trace.record(name, args, value)
        return value

    def get_approved_defaults() -> dict:
        """The approved default run parameters (stage-safe headline profile).

        Use these for any field the user leaves open; only ask when the user
        clearly wants something these defaults cannot express."""
        return _return("get_approved_defaults", {}, dict(PROFILE))

    def ask_user(question: str) -> str:
        """Ask the user ONE focused clarifying question. Hard budget: 2."""
        if len(state["questions"]) >= MAX_QUESTIONS:
            return _return("ask_user", {"question": question},
                           "(no more questions allowed — proceed with the "
                           "approved defaults or explain why you are blocked)")
        answer = sim_user.answer(question)
        state["questions"].append(question)
        return _return("ask_user", {"question": question}, answer)

    def compile_spec(canonical_prompt: str) -> dict:
        """Compile a fully-specified run request into a canonical RunSpec.

        Write one self-contained English sentence. Include 'stage-safe' to
        apply the approved defaults, then explicit overrides: an as-of date,
        'N paths', 'N% stress', or a conditioning clause such as 'EUR rates
        fall 50 basis points for the first 10 business days across two and
        five year tenors'."""
        result = compile_run_spec(canonical_prompt,
                                  provenance=DUMMY_PROVENANCE)
        if isinstance(result, Clarification):
            payload = {"compiled": False,
                       "is_quantitative": result.is_quantitative,
                       "missing_fields": list(result.missing_fields),
                       "message": result.message}
        else:
            spec_payload = {**canonical_run_payload(result),
                            "spec_hash": result.spec_hash}
            state["compiled"] = spec_payload
            payload = {"compiled": True, "spec_hash": result.spec_hash,
                       "payload": spec_payload}
        return _return("compile_spec",
                       {"canonical_prompt": canonical_prompt}, payload)

    functions = {fn.__name__: fn for fn in
                 (get_approved_defaults, ask_user, compile_spec)}
    return functions, state


def make_clarify_tools(sim_user, trace) -> tuple[list, dict]:
    from strands import tool

    functions, state = make_clarify_functions(sim_user, trace)
    return [tool(fn) for fn in functions.values()], state
