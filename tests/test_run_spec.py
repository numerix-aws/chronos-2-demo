import pytest

from chronos2_demo.run_spec import Clarification, compile_run_spec


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
