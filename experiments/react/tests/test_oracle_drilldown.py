import bundle
from tests.test_bundle import _mini_fixture
from trace import Trace

from oracles import drilldown


def _bundle() -> dict:
    return bundle.build_bundle(_mini_fixture())


def _trace_with_pfe() -> Trace:
    trace = Trace()
    trace.record("get_event", {"seq": 7},
                 {"name": "price_book", "scenario_role": "baseline",
                  "terminal": {"pfe_975": 2.0}})
    return trace


def test_faithful_ungrounded_armA_passes_without_trace():
    report = drilldown.score("Baseline terminal PFE is $2.00.", _bundle())
    assert report["passed"]


def test_invented_value_fails_faithfulness():
    report = drilldown.score("Baseline terminal PFE is $9.99.", _bundle())
    assert any(v["type"] == "invented_value" for v in report["violations"])


def test_grounded_claim_passes_with_trace():
    report = drilldown.score("Baseline terminal PFE is $2.00.", _bundle(),
                             trace=_trace_with_pfe())
    assert report["passed"]


def test_faithful_but_unfetched_claim_is_ungrounded():
    # $3.00 is the true ES (faithful), but the trace never fetched it.
    report = drilldown.score("Terminal ES is $3.00.", _bundle(),
                             trace=_trace_with_pfe())
    types = {v["type"] for v in report["violations"]}
    assert "ungrounded_claim" in types and "invented_value" not in types


def test_grounding_scales_unit_fractions_to_percent():
    trace = Trace()
    trace.record("get_diagnostics", {}, {"coverage": 0.88})
    assert drilldown.grounding_violations("Coverage was 88%.", trace) == []
    assert drilldown.grounding_violations("Coverage was 42%.", trace)


def test_no_numeric_claims_is_trivially_grounded():
    report = drilldown.score(
        "The blend reweights parametric paths toward stress.", _bundle(),
        trace=Trace())
    assert report["passed"]
