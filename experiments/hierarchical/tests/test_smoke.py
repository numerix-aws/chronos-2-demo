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
    assert director_row["failed_trials"] == 0
    assert list(tmp_path.glob("experiment_*.json"))


def test_harness_survives_failed_trial(tmp_path):
    import run_experiment
    call_count = [0]
    def failing_seams(model_id):
        seams = _fake_seams()
        orig_classify = seams.classify
        def classify_once_then_fail(user, summary):
            call_count[0] += 1
            if call_count[0] == 2:  # Fail on second turn of director arm
                raise RuntimeError("intentional failure")
            return orig_classify(user, summary)
        seams.classify = classify_once_then_fail
        return seams
    summary = run_experiment.run_matrix(
        trials=1, seams_factory=failing_seams,
        out_dir=tmp_path, session_filter=["s4_midsession_failure"])
    director_row = [r for r in summary["by_arm"] if r["arm"] == "director"][0]
    assert director_row["failed_trials"] >= 1
    assert list(tmp_path.glob("experiment_*.json"))


def test_harness_captures_clarify_outcome(tmp_path):
    import run_experiment
    summary = run_experiment.run_matrix(
        trials=1, seams_factory=lambda model_id: _fake_seams(),
        out_dir=tmp_path, session_filter=["s2_vague_quant"])
    results_file = list(tmp_path.glob("experiment_*.json"))[0]
    import json
    data = json.loads(results_file.read_text())
    director_turns = [t for r in data["results"] if r["arm"] == "director"
                      for t in r["turns"]]
    clarify_turn = [t for t in director_turns if t["route"] == "clarifier"][0]
    assert clarify_turn["clarify_outcome"] is not None
    assert "compiled" in clarify_turn["clarify_outcome"]
    assert "questions" in clarify_turn["clarify_outcome"]
    director_row = [r for r in summary["by_arm"] if r["arm"] == "director"][0]
    assert director_row.get("clarify_pass_rate") is not None


def test_clarifier_route_guard_when_no_resolves_to(tmp_path):
    import run_experiment
    def misclassifying_seams(model_id):
        seams = _fake_seams()
        orig_classify = seams.classify
        def classify_with_misclass(user, summary):
            # Misclassify turn 2 (out-of-scope) as what_if (always routes to clarifier)
            if "deploy this to our produ" in user:
                return SimpleNamespace(intent="what_if", confidence=0.9)
            return orig_classify(user, summary)
        seams.classify = classify_with_misclass
        return seams
    summary = run_experiment.run_matrix(
        trials=1, seams_factory=misclassifying_seams,
        out_dir=tmp_path, session_filter=["s1_clean_run_drilldown"])
    results_file = list(tmp_path.glob("experiment_*.json"))[0]
    import json
    data = json.loads(results_file.read_text())
    director_result = [r for r in data["results"] if r["arm"] == "director"][0]
    assert len(director_result["turns"]) == 3  # Session completed
    # Turn 2 was routed to clarifier but has no resolves_to
    turn2 = director_result["turns"][2]
    assert turn2["route"] == "clarifier"
    # Should use coded string
    assert turn2["reply"] in (
        "A run was compiled, but this turn was not scripted to execute one.",
        "Clarification needed."
    )
    # State should be unchanged from turn 1
    assert turn2["state_after"]["run_status"] == director_result["turns"][1]["state_after"]["run_status"]
