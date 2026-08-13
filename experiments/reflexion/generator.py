"""Tool-less Strands generator replicating the production interpretation stage."""
import json
import os
import pathlib
import time
from dataclasses import dataclass

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SYSTEM_PROMPT = (_REPO_ROOT / "agent" / "system_prompt.md").read_text(encoding="utf-8")
DEFAULT_MODEL_ID = os.environ.get("REFLEXION_MODEL_ID", "us.anthropic.claude-opus-5")


@dataclass
class Generation:
    text: str
    input_tokens: int | None
    output_tokens: int | None
    latency_s: float


def build_prompt(user_prompt: str, fixture: dict, feedback: str | None = None) -> str:
    if fixture.get("defect") == "partial_events":
        prompt = (
            f"{user_prompt}\n\nThe quantitative workflow emitted the following event "
            f"stream. Interpret the results: {fixture['raw_events_truncated']}"
        )
    else:
        payload = json.dumps(fixture["workflow"], sort_keys=True, allow_nan=False)
        prompt = (
            f"{user_prompt}\n\nThe deterministic quantitative workflow completed. "
            f"Interpret these structured results without changing any value: {payload}"
        )
    if feedback:
        prompt += (
            "\n\nA reviewer found problems with your previous answer. "
            f"Rewrite it, fixing every issue:\n{feedback}"
        )
    return prompt


def _make_agent(model_id: str):
    from strands import Agent
    from strands.models import BedrockModel

    # No temperature/top_p/top_k: removed on Opus 5 (400 if sent).
    return Agent(
        model=BedrockModel(model_id=model_id),
        system_prompt=SYSTEM_PROMPT,
        tools=[],
        callback_handler=None,
    )


def _usage(result) -> tuple[int | None, int | None]:
    try:
        usage = result.metrics.accumulated_usage
        return usage["inputTokens"], usage["outputTokens"]
    except (AttributeError, KeyError, TypeError):
        return None, None


def generate(
    user_prompt: str,
    fixture: dict,
    feedback: str | None = None,
    model_id: str | None = None,
) -> Generation:
    agent = _make_agent(model_id or DEFAULT_MODEL_ID)
    started = time.monotonic()
    result = agent(build_prompt(user_prompt, fixture, feedback))
    latency = time.monotonic() - started
    input_tokens, output_tokens = _usage(result)
    return Generation(str(result), input_tokens, output_tokens, latency)
