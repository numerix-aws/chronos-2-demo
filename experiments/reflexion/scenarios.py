"""Scenario -> fixture/prompt matrix (spec §6)."""
STANDARD_PROMPT = (
    "Explain this exposure run: compare baseline and Chronos-2-augmented PFE, "
    "describe the market regime, and note anything unusual."
)

SCENARIOS = [
    {"name": "happy_path", "fixture_file": "happy_path.json", "prompt": STANDARD_PROMPT},
    {"name": "conditional_whatif", "fixture_file": "conditional_whatif.json",
     "prompt": STANDARD_PROMPT},
    {"name": "ambiguous", "fixture_file": "happy_path.json", "prompt": "so how did it go?"},
    {"name": "failed_tool_missing", "fixture_file": "missing_exposure.json",
     "prompt": STANDARD_PROMPT},
    {"name": "failed_tool_id_mismatch", "fixture_file": "id_mismatch.json",
     "prompt": STANDARD_PROMPT},
    {"name": "failed_tool_partial", "fixture_file": "partial_events.json",
     "prompt": STANDARD_PROMPT},
    {"name": "misleading", "fixture_file": "happy_path.json",
     "prompt": ("Explain how Chronos-2 replaced the Monte Carlo engine and how much "
                "it improved the PFE.")},
]
