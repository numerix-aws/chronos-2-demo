"""The Director's only routing LLM: one schema-forced classification call."""
from typing import Literal

from pydantic import BaseModel, Field

import bridge

INTENT_SYSTEM = (
    "You are the intent classifier inside a demo control plane for a "
    "PFE/XVA quantitative workflow. Classify the user's message. Do not "
    "answer the message, do not run anything, do not add commentary — "
    "return only the classification."
)

_DESCRIPTIONS = {
    "quant_run": "asks to run/compute a quantitative scenario or exposure run",
    "what_if": "asks for a conditional what-if run (conditioning on a regime/anchor)",
    "followup_qa": "asks about results, numbers, diagnostics, or implications of a run",
    "failure_help": "asks what went wrong / why a run failed or stalled",
    "out_of_scope": "asks for something this demo does not do (deploys, prod changes, unrelated work)",
    "general_chat": "greeting or small talk with no task content",
}


class IntentVerdict(BaseModel):
    intent: Literal["quant_run", "what_if", "followup_qa",
                    "failure_help", "out_of_scope", "general_chat"]
    confidence: float = Field(ge=0.0, le=1.0)


def build_intent_prompt(user_text: str, state_summary: str) -> str:
    labels = "\n".join(f"- {name}: {desc}" for name, desc in _DESCRIPTIONS.items())
    return (
        f"Session state: {state_summary}\n\nClassify this user message into "
        f"exactly one intent. Do not answer the question, do not run anything, "
        f"do not add commentary:\n{labels}\n\nUser message:\n---\n{user_text}\n---"
    )


def classify(user_text: str, state_summary: str,
             model_id: str | None = None) -> IntentVerdict:
    from strands import Agent
    from strands.models import BedrockModel

    agent = Agent(
        model=BedrockModel(model_id=model_id or bridge.DEFAULT_MODEL_ID,
                           max_tokens=8192),
        system_prompt=INTENT_SYSTEM,
        tools=[],
        callback_handler=None,
    )
    return agent.structured_output(
        IntentVerdict, build_intent_prompt(user_text, state_summary))
