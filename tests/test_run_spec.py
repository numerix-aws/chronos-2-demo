import pytest

from chronos2_demo.run_spec import (
    Clarification,
    canonical_run_payload,
    compile_run_spec,
    compute_spec_hash,
)


PROVENANCE = {
    "market_snapshot_id": "market-v1",
    "market_sha256": "a" * 64,
    "covariate_snapshot_id": "cov-v1",
    "covariate_sha256": "b" * 64,
    "chronos_endpoint": "chronos2-demo",
    "chronos_model_version": "chronos-2",
    "baseline_image_digest": "sha256:baseline",
    "chronos_image_digest": "sha256:chronos",
    "agent_image_digest": "sha256:agent",
    "book_version": "cross_asset_demo_v1",
    "blend_version": "importance_weight_v1",
    "pricing_version": "cross_asset_v1",
    "tool_bundle_version": "git:test",
    "strands_version": "1.30.0",
}
HEADLINE_PROMPT = (
    "Run the stage-safe headline demo for September 30, 2022. Use five years "
    "of trading history, project one trading year into the future, generate 500 "
    "scenarios with each engine, and apply a 53.05% stress weight."
)
EXPECTED_SPEC_HASH = "1add95a87e0bc214d85f668b47c6fc0dfd7c5803a544dfd0cf1552903658de84"


@pytest.mark.parametrize("prompt", [
    "Run the stage-safe headline demo for September 30, 2022. Use five years "
    "of trading history, project one trading year into the future, generate 500 "
    "scenarios with each engine, and apply a 53.05% stress weight.",
    "Using the stage-safe settings as of 2022-09-30, look back 1260 trading "
    "days, forecast 252 trading days, "
    "use 500 paths per model, and blend with stress weight 0.5305.",
    "Use the stage safe setup on Sep 30 2022 with a five trading-year lookback, "
    "a one trading-year horizon, 500 simulations per engine and 53.05 percent stress.",
])
def test_equivalent_prompts_compile_to_same_spec_hash(prompt):
    spec = compile_run_spec(prompt, provenance=PROVENANCE, execution_id="run-a")
    assert not isinstance(spec, Clarification)
    assert spec.spec_hash == EXPECTED_SPEC_HASH
    assert spec.lookback_days == 1260
    assert spec.horizon == 252
    assert spec.n_paths == 500
    assert spec.w_stress == pytest.approx(0.5305)


def test_independent_executions_share_spec_hash_but_not_execution_id():
    first = compile_run_spec(HEADLINE_PROMPT, provenance=PROVENANCE, execution_id="run-a")
    second = compile_run_spec(HEADLINE_PROMPT, provenance=PROVENANCE, execution_id="run-b")
    assert first.spec_hash == second.spec_hash
    assert first.execution_id != second.execution_id


@pytest.mark.parametrize("prompt,field", [
    ("Run exposure for September 2022 with 500 paths.", "as_of_date"),
    ("Run exposure as of 2022-09-30 with a one-year horizon.", "lookback_days"),
    ("Run exposure as of 2022-09-30 with five years of history.", "horizon"),
    ("Run exposure as of 2022-09-30 with five years of history and one year ahead.", "n_paths"),
])
def test_ambiguous_quantitative_prompt_fails_closed(prompt, field):
    result = compile_run_spec(prompt, provenance=PROVENANCE)
    assert isinstance(result, Clarification)
    assert field in result.missing_fields


def test_greeting_does_not_compile_as_quantitative():
    result = compile_run_spec("Say hello and do not run tools.", provenance=PROVENANCE)
    assert isinstance(result, Clarification)
    assert result.is_quantitative is False


def test_rate_what_if_normalizes_to_existing_conditioning_contract():
    prompt = (
        "Using the same stage-safe setup, what happens if EUR rates fall 50 basis "
        "points across the two-, five-, and ten-year tenors for the first 30 business days?"
    )
    spec = compile_run_spec(prompt, provenance=PROVENANCE, execution_id="run-what-if")
    assert not isinstance(spec, Clarification)
    assert spec.conditioning == {
        "series_shifts": {"EUR_2Y": -0.5, "EUR_5Y": -0.5, "EUR_10Y": -0.5},
        "n_anchor_days": 30,
    }
    assert spec.w_stress == 1.0


def test_run_spec_nested_mappings_cannot_mutate_payload_or_hash():
    provenance = dict(PROVENANCE)
    spec = compile_run_spec(
        "Using the same stage-safe setup, what happens if EUR rates fall 50 basis "
        "points across the two-, five-, and ten-year tenors for the first 30 business days?",
        provenance=provenance,
        execution_id="run-what-if",
    )
    assert not isinstance(spec, Clarification)
    assert spec.provenance == PROVENANCE

    with pytest.raises(TypeError):
        spec.provenance["market_snapshot_id"] = "mutated"
    with pytest.raises(TypeError):
        spec.conditioning["series_shifts"]["EUR_2Y"] = 0.0

    payload = canonical_run_payload(spec)
    payload["provenance"]["market_snapshot_id"] = "mutated"
    payload["conditioning"]["series_shifts"]["EUR_2Y"] = 0.0
    assert canonical_run_payload(spec)["provenance"] == PROVENANCE
    assert compute_spec_hash(canonical_run_payload(spec)) == spec.spec_hash


@pytest.mark.parametrize("prompt", [
    "Run the stage-safe headline demo for 2022-02-30.",
    "Run the stage-safe headline demo for September 2022.",
    "Run the stage-safe headline demo for 2022-09.",
])
def test_invalid_or_ambiguous_explicit_date_fails_closed(prompt):
    result = compile_run_spec(
        prompt,
        provenance=PROVENANCE,
    )
    assert isinstance(result, Clarification)
    assert "as_of_date" in result.missing_fields


@pytest.mark.parametrize("prompt,field", [
    ("Run the stage-safe headline demo for 2022-09-30 and 2022-10-03.", "as_of_date"),
    ("Run the stage-safe headline demo with 500 paths and 600 scenarios.", "n_paths"),
    (
        "Run the stage-safe headline demo, forecast 252 trading days and 504 trading days ahead.",
        "horizon",
    ),
    (
        "Run the stage-safe headline demo with five years of history and 504 trading days of history.",
        "lookback_days",
    ),
    ("Run the stage-safe headline demo with stress weight 0.5 and 60% stress.", "w_stress"),
])
def test_conflicting_explicit_values_fail_closed(prompt, field):
    result = compile_run_spec(prompt, provenance=PROVENANCE)
    assert isinstance(result, Clarification)
    assert field in result.missing_fields


def test_single_explicit_profile_override_is_applied():
    spec = compile_run_spec(
        "Run the stage-safe headline demo with 600 scenarios.",
        provenance=PROVENANCE,
        execution_id="run-override",
    )
    assert not isinstance(spec, Clarification)
    assert spec.n_paths == 600


def test_exposure_use_case_question_does_not_compile_as_quantitative():
    result = compile_run_spec(
        "What exposure use cases does Chronos-2 support for XVA?",
        provenance=PROVENANCE,
    )
    assert isinstance(result, Clarification)
    assert result.is_quantitative is False


def test_expose_request_compiles_as_quantitative():
    spec = compile_run_spec(
        "Expose the stage-safe headline demo.",
        provenance=PROVENANCE,
        execution_id="run-expose",
    )
    assert not isinstance(spec, Clarification)


def test_stress_use_case_question_does_not_compile_as_quantitative():
    result = compile_run_spec(
        "What stress use cases does this demo support?",
        provenance=PROVENANCE,
    )
    assert isinstance(result, Clarification)
    assert result.is_quantitative is False


def test_stress_test_use_case_question_does_not_compile_as_quantitative():
    result = compile_run_spec(
        "What stress test use cases does this demo support?",
        provenance=PROVENANCE,
    )
    assert isinstance(result, Clarification)
    assert result.is_quantitative is False


def test_stress_request_compiles_as_quantitative():
    spec = compile_run_spec(
        "Stress the stage-safe headline demo.",
        provenance=PROVENANCE,
        execution_id="run-stress",
    )
    assert not isinstance(spec, Clarification)


def test_run_a_stress_test_compiles_as_quantitative():
    spec = compile_run_spec(
        "Run a stress test using the stage-safe headline demo.",
        provenance=PROVENANCE,
        execution_id="run-stress-test",
    )
    assert not isinstance(spec, Clarification)


def test_canonical_run_payload_excludes_transient_identity_fields():
    spec = compile_run_spec(HEADLINE_PROMPT, provenance=PROVENANCE, execution_id="run-a")
    assert not isinstance(spec, Clarification)
    payload = canonical_run_payload(spec)
    assert payload["provenance"] == PROVENANCE
    assert "execution_id" not in payload
    assert "spec_hash" not in payload


def test_compute_spec_hash_is_stable_for_canonical_payloads():
    spec = compile_run_spec(HEADLINE_PROMPT, provenance=PROVENANCE, execution_id="run-a")
    assert not isinstance(spec, Clarification)
    payload = canonical_run_payload(spec)
    assert compute_spec_hash(payload) == spec.spec_hash
    assert compute_spec_hash({**payload, "execution_id": "run-b", "spec_hash": "ignored"}) == spec.spec_hash
