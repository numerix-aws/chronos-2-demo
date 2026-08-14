"""Role → scenario matrix (spec §7)."""
import json
import pathlib

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

CLARIFY = ("fully_specified", "one_field_missing", "vague_stress",
           "hopelessly_vague", "whatif_conditioning", "misleading_premise")
TRIAGE = ("missing_exposure", "id_mismatch", "partial_events",
          "poll_timeout", "hash_mismatch")
DRILLDOWN = (
    {"id": "pfe_delta", "bundle": "drilldown_happy",
     "question": "Why did the augmented PFE end up where it did relative to "
                 "the baseline? Quantify the change."},
    {"id": "blend_trust", "bundle": "drilldown_happy",
     "question": "Is the blended result trustworthy? What do the coverage "
                 "diagnostics say?"},
    {"id": "w_stress", "bundle": "drilldown_happy",
     "question": "What stress weight drove the blend, and what does it mean "
                 "for how the paths were reweighted?"},
    {"id": "provenance", "bundle": "drilldown_happy",
     "question": "Which artifacts, URIs and hashes back the augmented "
                 "terminal number?"},
    {"id": "conditional", "bundle": "drilldown_conditional",
     "question": "How did the what-if conditioning show up in the "
                 "chronos-only exposure result?"},
)


def _load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_clarify(name: str) -> dict:
    return _load(FIXTURES / "clarify" / f"{name}.json")


def load_triage(name: str) -> dict:
    return _load(FIXTURES / f"triage_{name}.json")


def load_drilldown(item: dict) -> tuple[dict, str]:
    return _load(FIXTURES / f"{item['bundle']}.json"), item["question"]
