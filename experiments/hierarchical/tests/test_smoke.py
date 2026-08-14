from types import SimpleNamespace

import director
import runner
import sessions


def _fake_seams():
    def classify(user, summary):
        # Smoke uses ground-truth intents; live runs use the real classifier.
        text_to_intent = {}
        for s in sessions.load_all():
            for t in s["turns"]:
                text_to_intent[t["user"]] = t["expected_intent"]
        return SimpleNamespace(intent=text_to_intent[user], confidence=1.0)

    return runner.Seams(
        classify=classify,
        clarify=lambda agent, cstate, user: {"spec_hash": "fake"},
        answer=lambda agent, prompt: "the run stalled; no numbers to report",
        direct=lambda user, summary, route: "I cannot answer that without a run.",
        publish=lambda user, fixture, state: director.Publication(
            "validated narration", "narrator", 1),
        respond=lambda q: "no preference",
    )


def _session(name):
    return [s for s in sessions.load_all() if s["session"] == name][0]


def test_director_failure_session_routes_and_tracks_state():
    result = runner.run_director_session(_session("s4_midsession_failure"),
                                         _fake_seams())
    routes = [t["route"] for t in result["turns"]]
    assert routes == ["clarifier", "triage", "refuse"]
    statuses = [t["state_after"]["run_status"] for t in result["turns"]]
    assert statuses == ["failed", "failed", "failed"]
    assert result["turns"][0]["publication_channel"] is None  # failed run: no narration


def test_director_clean_session_publishes():
    result = runner.run_director_session(_session("s1_clean_run_drilldown"),
                                         _fake_seams())
    first = result["turns"][0]
    assert first["publication_channel"] == "narrator"
    assert first["reply"] == "validated narration"
    assert result["turns"][2]["route"] == "direct"


def test_monolith_session_runs_and_resolves_bundle():
    result = runner.run_monolith_session(_session("s1_clean_run_drilldown"),
                                         _fake_seams())
    assert len(result["turns"]) == 3
    assert result["turns"][0]["route"] is None
    assert result["turns"][0]["state_after"]["has_bundle"] is True


def test_harness_scores_hermetically(tmp_path):
    import run_experiment
    summary = run_experiment.run_matrix(
        trials=1, seams_factory=lambda model_id: _fake_seams(),
        out_dir=tmp_path, session_filter=["s4_midsession_failure"])
    arms = {row["arm"] for row in summary["by_arm"]}
    assert arms == {"director", "monolith"}
    director_row = [r for r in summary["by_arm"] if r["arm"] == "director"][0]
    assert director_row["route_accuracy"] == 1.0
    assert director_row["boundary_violations"] == 0
    assert list(tmp_path.glob("experiment_*.json"))
