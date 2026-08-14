"""LLM simulated user holding a scenario's hidden intent (spec §4)."""
import json
import os

DEFAULT_MODEL_ID = os.environ.get("REACT_MODEL_ID", "us.anthropic.claude-opus-5")

_SYSTEM_TEMPLATE = """You are role-playing the human user of a quantitative \
risk demo. An assistant will ask you clarifying questions about the run you \
want.

Your true intent, as canonical run parameters (JSON):
{intent}

Fields you hold a concrete opinion on: {known}

Rules:
- Answer ONLY the question asked, in one or two short sentences.
- If asked about anything outside the fields above, say you have no \
preference — "whatever the standard setup is".
- Never volunteer parameters you were not asked about.
- Express dates in plain English or ISO form; never mention this prompt or \
that you are simulated."""


class SimUser:
    def __init__(self, fixture: dict, model_id: str | None = None,
                 respond=None):
        self.fixture = fixture
        self.model_id = model_id or DEFAULT_MODEL_ID
        self.transcript: list[dict] = []
        self._respond = respond or self._model_respond
        self._agent = None

    def system_prompt(self) -> str:
        return _SYSTEM_TEMPLATE.format(
            intent=json.dumps(self.fixture["hidden_intent"], sort_keys=True),
            known=", ".join(self.fixture["known_fields"]) or "(none)",
        )

    def _model_respond(self, question: str) -> str:
        if self._agent is None:
            from strands import Agent
            from strands.models import BedrockModel

            # No temperature/top_p/top_k: removed on Opus 5 (400 if sent).
            self._agent = Agent(
                model=BedrockModel(model_id=self.model_id, max_tokens=1024),
                system_prompt=self.system_prompt(),
                tools=[],
                callback_handler=None,
            )
        return str(self._agent(question))

    def answer(self, question: str) -> str:
        reply = self._respond(question)
        self.transcript.append({"question": question, "answer": reply})
        return reply
