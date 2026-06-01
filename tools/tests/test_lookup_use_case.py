import json
from pathlib import Path
import pytest
from tools.lambda_.lookup_use_case import handler


def test_lookup_returns_brief_for_known_topic(monkeypatch, tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("KNOWLEDGE_DIR", str(repo_root / "agent" / "knowledge"))
    out = handler.handler({"topic": "stress_test_design"}, None)
    assert out["status"] == "ok"
    assert "stress" in out["result"]["markdown"].lower()
    assert out["result"]["topic"] == "stress_test_design"


def test_lookup_lists_topics_when_no_topic_given(monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("KNOWLEDGE_DIR", str(repo_root / "agent" / "knowledge"))
    out = handler.handler({}, None)
    assert out["status"] == "ok"
    assert isinstance(out["result"]["topics"], list)
    assert "stress_test_design" in out["result"]["topics"]


def test_lookup_rejects_unknown_topic(monkeypatch):
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("KNOWLEDGE_DIR", str(repo_root / "agent" / "knowledge"))
    out = handler.handler({"topic": "made_up"}, None)
    assert out["status"] == "error"
