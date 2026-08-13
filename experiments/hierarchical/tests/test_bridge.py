"""Prerequisite gate: fails loudly if reflexion/react are absent or drifted."""
import bridge


def test_reflexion_interfaces_present():
    assert callable(bridge.reflexion_generator.generate)
    assert callable(bridge.reflexion_validator.validate)
    assert callable(bridge.reflexion_validator.extract_money)
    assert callable(bridge.reflexion_validator.extract_percents)
    assert callable(bridge.reflexion_critic.critique)
    assert callable(bridge.reflexion_loop.run_reflexion)
    assert callable(bridge.reflexion_loop.format_feedback)


def test_react_interfaces_present():
    assert callable(bridge.react_tools.make_evidence_tools)
    assert callable(bridge.react_trace.Trace)
    assert callable(bridge.react_clarify_tools.make_clarify_tools)
    assert len(bridge.react_clarify_tools.DUMMY_PROVENANCE) == 14
    assert callable(bridge.react_sim_user.SimUser)
    assert callable(bridge.react_oracle_triage.score)
    assert callable(bridge.react_oracle_drilldown.score)


def test_react_bundles_load():
    for name in ("drilldown_happy", "drilldown_conditional",
                 "triage_poll_timeout", "triage_hash_mismatch"):
        b = bridge.load_react_bundle(name)
        assert "run_spec" in b and "events" in b and "exposure" in b


def test_reflexion_fixtures_load():
    fx = bridge.load_reflexion_fixture("happy_path")
    assert "workflow" in fx and "expected_posture" in fx


def test_provenance_shape():
    assert len(bridge.PROVENANCE) == 14
    assert set(bridge.PROVENANCE.values()) == {"experiment"}
