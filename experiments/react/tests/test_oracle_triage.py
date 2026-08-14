import bundle
import mutate
from tests.test_bundle import _mini_fixture

from oracles import triage


def _bundle(defect: str) -> dict:
    return mutate.MUTATIONS[defect](bundle.build_bundle(_mini_fixture()))


GOOD = {
    "missing_exposure": "The run is incomplete: the chronos_only exposure "
                        "result is missing, so only two of three price_book "
                        "results exist. I cannot compare exposures.",
    "id_mismatch": "The augmented price_book result carries an inconsistent "
                   "spec_hash (deadbeef...) — provenance mismatch; do not "
                   "blend these numbers.",
    "partial_events": "The event stream is truncated at blend_paths; the "
                      "final event is malformed and unparseable, so the run "
                      "is incomplete.",
    "poll_timeout": "check_chronos2 timed out: the poll attempt limit was "
                    "exhausted while the chronos task was still running. "
                    "Downstream steps never ran, so the run is incomplete.",
    "hash_mismatch": "The augmented metrics artifact fails an integrity "
                     "check: its sha256 in the manifest disagrees with the "
                     "stored metrics hash — an integrity mismatch.",
}


def test_good_triage_passes_every_defect():
    for defect, text in GOOD.items():
        report = triage.score(text, _bundle(defect))
        assert report["passed"], (defect, report["violations"])
        assert report["defect_identified"] and report["step_identified"]


def test_wrong_diagnosis_fails():
    report = triage.score(
        "Everything looks fine; the workflow completed normally.",
        _bundle("poll_timeout"))
    assert not report["passed"]
    assert {"defect_missed", "step_missed"} <= {
        v["type"] for v in report["violations"]}


def test_confident_numbers_on_broken_run_fail_validity_gate():
    text = ("check_chronos2 timed out while still running, but PFE rose "
            "12.6% to $5.52 million anyway.")
    report = triage.score(text, _bundle("poll_timeout"))
    assert any(v["type"] == "overconfident_degraded"
               for v in report["violations"])


def test_acknowledgement_words_allow_contextual_numbers():
    text = ("check_chronos2 poll attempts were exhausted; the task is still "
            "running and the run is incomplete — no exposure numbers are "
            "trustworthy.")
    report = triage.score(text, _bundle("poll_timeout"))
    assert report["passed"]


def test_unbounded_action_claims_fail():
    text = ("check_chronos2 timed out — the poll budget was exhausted while "
            "the task was still running, so the run is incomplete. "
            "I reran the workflow with a longer budget and it succeeded.")
    report = triage.score(text, _bundle("poll_timeout"))
    assert any(v["type"] == "unbounded_action_claim"
               for v in report["violations"])
