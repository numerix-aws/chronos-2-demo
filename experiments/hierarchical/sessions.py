"""Session scripts + the fixture DAG (the only 'execution' in this experiment)."""
import json
import pathlib

import bridge

INTENTS = frozenset({"quant_run", "what_if", "followup_qa",
                     "failure_help", "out_of_scope", "general_chat"})
ROUTES = frozenset({"clarifier", "qa", "triage", "direct", "refuse"})
SCORE_KINDS = frozenset({"none", "narration", "qa", "qa_premise",
                         "triage", "refusal", "chat"})
SESSIONS_DIR = pathlib.Path(__file__).resolve().parent / "fixtures" / "sessions"


def _validate(session: dict) -> dict:
    assert 2 <= len(session["turns"]) <= 4, session["session"]
    for turn in session["turns"]:
        assert turn["expected_intent"] in INTENTS
        assert turn["expected_route"] in ROUTES
        assert turn["score"]["kind"] in SCORE_KINDS
        assert isinstance(turn["expected_state_after"], dict)
        if turn["expected_route"] == "clarifier":
            assert turn["resolves_to"]["outcome"] in {"complete", "failed"}
    return session


def load_all() -> list[dict]:
    paths = sorted(SESSIONS_DIR.glob("s*.json"))
    return [_validate(json.loads(p.read_text())) for p in paths]


def _degraded_fixture_from_bundle(bundle: dict) -> dict:
    """Reflexion-shaped fixture for narrating a run whose bundle is defective."""
    return {
        "workflow": {
            "run_spec": bundle["run_spec"],
            "exposure": bundle["exposure"],
            "diagnostics": bundle["diagnostics"],
        },
        "expected_posture": "degraded",
        "defect": bundle["defect"],
    }


def resolve_outcome(resolves_to: dict):
    """Fixture DAG: compiled spec -> pre-labeled (bundle, fixture, outcome)."""
    bundle = bridge.load_react_bundle(resolves_to["react_bundle"])
    outcome = resolves_to["outcome"]
    if resolves_to.get("reflexion_fixture"):
        fixture = bridge.load_reflexion_fixture(resolves_to["reflexion_fixture"])
    elif outcome == "complete":
        fixture = _degraded_fixture_from_bundle(bundle)
    else:
        fixture = None
    return bundle, fixture, outcome
