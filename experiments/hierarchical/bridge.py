"""Single point of cross-experiment reuse (read-only, by sys.path)."""
import importlib
import importlib.util
import json
import os
import pathlib
import sys

_EXPERIMENTS = pathlib.Path(__file__).resolve().parent.parent
REFLEXION_DIR = _EXPERIMENTS / "reflexion"
REACT_DIR = _EXPERIMENTS / "react"

for _dir in (REFLEXION_DIR, REACT_DIR):
    if str(_dir) not in sys.path:
        sys.path.append(str(_dir))

# Reflexion modules have no stdlib/local name collisions — plain imports
# resolve from the appended reflexion dir. Colliding names (mutate,
# scenarios, run_experiment) are never imported through the bridge.
reflexion_generator = importlib.import_module("generator")
reflexion_validator = importlib.import_module("validator")
reflexion_critic = importlib.import_module("critic")
reflexion_loop = importlib.import_module("loop")


def _load_react(alias: str, filename: str):
    # React top-level modules load by explicit file path: `trace` collides
    # with the Python stdlib module (which wins on sys.path order and may
    # already sit in sys.modules), so name-based imports are unsafe here.
    spec = importlib.util.spec_from_file_location(alias, REACT_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


react_trace = _load_react("react_trace", "trace.py")
react_tools = _load_react("react_tools", "tools.py")
react_clarify_tools = _load_react("react_clarify_tools", "clarify_tools.py")
react_sim_user = _load_react("react_sim_user", "sim_user.py")
# react's `oracles` package is safe by name (no stdlib/local collision —
# hierarchical's own package is called `scoring/` precisely for this).
react_oracle_triage = importlib.import_module("oracles.triage")
react_oracle_drilldown = importlib.import_module("oracles.drilldown")

DEFAULT_MODEL_ID = os.environ.get("HIER_MODEL_ID", "us.anthropic.claude-opus-5")
PROVENANCE = dict(react_clarify_tools.DUMMY_PROVENANCE)


def load_react_bundle(name: str) -> dict:
    return json.loads((REACT_DIR / "fixtures" / f"{name}.json").read_text())


def load_reflexion_fixture(name: str) -> dict:
    return json.loads((REFLEXION_DIR / "fixtures" / f"{name}.json").read_text())
