"""Keep presenter prompts natural while orchestration stays in agent policy."""
import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SCRIPT = (REPO / "docs/demo/demo-first-presenter-script.md").read_text()
E2E = (REPO / "frontend/tests/e2e/happy_path.spec.ts").read_text()


def _script_prompt(heading: str) -> str:
    section = SCRIPT.split(heading, 1)[1]
    match = re.search(r"Paste this exact prompt into the chat:\n\n```text\n(.*?)\n```", section, re.S)
    assert match, f"prompt not found after {heading}"
    return match.group(1)


def _e2e_prompt(name: str) -> str:
    match = re.search(rf"const {name} =\n\s*`(.*?)`;", E2E, re.S)
    assert match, f"template-literal prompt {name} not found"
    return match.group(1)


def _assert_natural(prompt: str) -> None:
    forbidden = (
        "as_of_date=",
        "lookback_days=",
        "horizon=",
        "n_paths=",
        "w_stress=",
        "n_components=",
        "seed=",
        "spec=",
        "metrics_uri",
        "image_uri",
        "tool-trace",
    )
    assert not [token for token in forbidden if token in prompt]


def test_headline_prompt_uses_business_language_in_script_and_e2e():
    script_prompt = _script_prompt("## Demo Step 1 - Start In The App")
    e2e_prompt = _e2e_prompt("HEADLINE_PROMPT")
    assert script_prompt == e2e_prompt
    _assert_natural(script_prompt)
    assert "five years of trading history" in script_prompt
    assert "one trading year" in script_prompt
    assert "500 scenarios" in script_prompt
    assert "53.05% stress weight" in script_prompt


def test_what_if_prompt_uses_business_language_in_script_and_e2e():
    script_prompt = _script_prompt("## Demo Step 4 - Natural-Language What-If")
    e2e_prompt = _e2e_prompt("WHAT_IF_PROMPT")
    assert script_prompt == e2e_prompt
    _assert_natural(script_prompt)
    assert "50 basis points" in script_prompt
    assert "first 30 business days" in script_prompt
    assert "two-, five-, and ten-year" in script_prompt
    assert "same stage-safe setup" in script_prompt
