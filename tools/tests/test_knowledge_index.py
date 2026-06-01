"""The knowledge index must list every brief, and every listed file must exist."""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = REPO_ROOT / "agent" / "knowledge"


def test_index_lists_all_briefs():
    index = json.loads((KNOWLEDGE_DIR / "index.json").read_text())
    expected = {
        "stress_test_design",
        "im_vm_forecasting",
        "frtb_ima_es",
        "market_data_gap_filling",
        "scenario_limits",
        "long_context_windows",
        "temporal_hierarchies",
    }
    assert set(index.keys()) == expected


def test_each_indexed_brief_file_exists_and_nonempty():
    index = json.loads((KNOWLEDGE_DIR / "index.json").read_text())
    for topic, meta in index.items():
        path = KNOWLEDGE_DIR / meta["file"]
        assert path.exists(), f"missing brief file for {topic}"
        body = path.read_text().strip()
        assert len(body) > 100, f"brief {topic} is suspiciously short"


def test_each_brief_has_a_one_line_summary():
    index = json.loads((KNOWLEDGE_DIR / "index.json").read_text())
    for topic, meta in index.items():
        assert "summary" in meta and len(meta["summary"]) > 20
