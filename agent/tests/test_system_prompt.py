"""Validate the prompt boundary around deterministic quantitative execution."""
from pathlib import Path


PROMPT = (Path(__file__).resolve().parents[1] / "system_prompt.md").read_text()


def _section(title: str) -> str:
    start = PROMPT.index(f"## {title}")
    end = PROMPT.find("\n## ", start + 3)
    return PROMPT[start:] if end == -1 else PROMPT[start:end]


def test_prompt_delegates_quantitative_execution_to_the_runtime():
    section = _section("Deterministic quantitative results")
    assert "deterministic runtime workflow" in section.lower()
    assert "not select" in section.lower()
    assert "baseline" in section.lower()
    assert "chronos-only" in section.lower()
    assert "augmented" in section.lower()
    assert "ambiguous" in section.lower()
    assert "before the model" in section.lower()


def test_prompt_treats_structured_results_as_immutable_numerical_truth():
    section = _section("Deterministic quantitative results")
    assert "numerical truth" in section.lower()
    assert "never restate or alter" in section.lower()
    for forbidden in ("exposure values", "diagnostics", "image uris", "tool success"):
        assert forbidden in section.lower()
    assert "never fabricate" in section.lower()


def test_prompt_keeps_automatic_visibility_without_ui_markers():
    assert "structured" in PROMPT.lower()
    assert "automatic" in PROMPT.lower()
    assert "::tool-trace" not in PROMPT
    assert "exposure_summary" not in PROMPT
    assert "Markdown image" not in PROMPT


def test_prompt_preserves_lookup_catalog_discovery_for_nonquantitative_questions():
    assert "`lookup_use_case([topic])`" in PROMPT
    assert "omit `topic` first to discover the catalog" in PROMPT
