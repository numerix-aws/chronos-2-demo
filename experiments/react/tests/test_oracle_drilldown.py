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


def _bundle_with_attribution() -> dict:
    fx = _mini_fixture()
    fx["workflow"]["diagnostics"] = {
        "execution_id": "e" * 32,
        "attribution": {"final_blend": {"delta_pfe_975_pct": 12.59,
                                        "delta_pfe_975": 617241.67}},
        "factor_coverage": {"nominal": 0.95},
    }
    return bundle.build_bundle(fx)


def test_structural_quantile_label_accepted():
    report = drilldown.score("PFE at the 97.5% quantile is $2.00.", _bundle())
    assert report["passed"], report["violations"]


def test_attribution_numbers_accepted():
    report = drilldown.score(
        "The final blend moved PFE by 12.59% ($617,241.67) against the "
        "95% nominal coverage.", _bundle_with_attribution())
    assert report["passed"], report["violations"]


def test_truncated_hash_prefix_accepted():
    # 16-char prefix of the known paths_sha256 ("b" * 64).
    report = drilldown.score(
        f"Backed by the paths artifact {'b' * 16}.", _bundle())
    assert report["passed"], report["violations"]


def test_unknown_hash_still_flagged():
    report = drilldown.score(
        "Backed by the artifact deadbeefdeadbeef.", _bundle())
    assert any(v["type"] == "wrong_identifier"
               for v in report["violations"])


def test_negative_delta_cited_as_positive_reduction_accepted():
    fx = _mini_fixture()
    fx["workflow"]["diagnostics"] = {
        "execution_id": "e" * 32,
        "attribution": {"reweighted_chronos": {"delta_pfe_975_pct": -19.83}},
    }
    report = drilldown.score(
        "Reweighting cut chronos PFE by 19.83%.", bundle.build_bundle(fx))
    assert report["passed"], report["violations"]


def test_integer_rounding_of_payload_value_accepted():
    fx = _mini_fixture()
    fx["workflow"]["diagnostics"] = {
        "execution_id": "e" * 32,
        "attribution": {"reweighted_parametric": {"delta_pfe_975_pct": 24.48}},
    }
    b = bundle.build_bundle(fx)
    assert drilldown.score("Roughly a 24% lift.", b)["passed"]
    report = drilldown.score("Roughly a 23% lift.", b)
    assert any(v["type"] == "wrong_value" for v in report["violations"])


def test_decimal_float_fragment_is_not_an_identifier():
    report = drilldown.score(
        "Coverage came in at 48.614544536470596% of nominal... "
        "wait, no percent claims here: value 614544536470596 cited raw.",
        _bundle())
    assert not any(v["type"] == "wrong_identifier"
                   for v in report["violations"])


def test_provenance_hash_from_run_spec_accepted():
    fx = _mini_fixture()
    fx["workflow"]["run_spec"]["provenance"] = {"market_sha256": "c0ffee" * 8}
    b = bundle.build_bundle(fx)
    # 24-char prefix of the 48-char provenance hash.
    report = drilldown.score(
        f"Snapshotted market data ({'c0ffee' * 4}) backs the run.", b)
    assert report["passed"], report["violations"]


def test_derived_percent_change_between_terminals_accepted():
    fx = _mini_fixture()
    fx["workflow"]["exposure"]["augmented"]["terminal"]["pfe_975"] = 3.0
    b = bundle.build_bundle(fx)
    # (3.0 - 2.0) / 2.0 = +50% between baseline and augmented terminals.
    report = drilldown.score(
        "Augmented terminal PFE of $3.00 sits 50.0% above the baseline "
        "$2.00.", b)
    assert report["passed"], report["violations"]


def test_event_counters_do_not_ground_claims():
    trace = Trace()
    trace.record("get_event", {"seq": 7},
                 {"seq": 7, "attempt": 7, "terminal": {"pfe_975": 2.0}})
    assert drilldown.grounding_violations("$2.00 held.", trace) == []
    assert drilldown.grounding_violations("$7.00 held.", trace)


def test_structural_percent_grounded_without_fetch():
    assert drilldown.grounding_violations(
        "At the 97.5% quantile.", Trace()) == []


def test_no_numeric_claims_is_trivially_grounded():
    report = drilldown.score(
        "The blend reweights parametric paths toward stress.", _bundle(),
        trace=Trace())
    assert report["passed"]
