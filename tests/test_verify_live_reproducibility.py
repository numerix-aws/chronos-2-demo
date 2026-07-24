from __future__ import annotations

from copy import deepcopy
import json

import pytest

from scripts import verify_live_reproducibility as verifier


ROLES = ("baseline", "chronos_only", "augmented")
SPEC_HASH = "f" * 64
PROVENANCE = {
    "market_snapshot_id": "curated-market-v1",
    "market_sha256": "a" * 64,
    "covariate_snapshot_id": "curated-covariates-v1",
    "covariate_sha256": "b" * 64,
    "chronos_endpoint": "chronos2-demo-ep",
    "chronos_model_version": "chronos-2",
    "baseline_image_digest": "sha256:" + "c" * 64,
    "chronos_image_digest": "sha256:" + "d" * 64,
    "agent_image_digest": "sha256:" + "e" * 64,
    "book_version": "cross_asset_demo_v1",
    "blend_version": "importance_weight_v1",
    "pricing_version": "cross_asset_v1",
    "tool_bundle_version": "git:63dda42bc8373c63398a298d76118d8c3787c16c",
    "strands_version": "1.30.0",
}


def _run_spec(execution_id: str) -> dict[str, object]:
    return {
        "schema_version": "1",
        "profile": "stage_safe_headline_v1",
        "as_of_date": "2022-09-30",
        "lookback_days": 1260,
        "horizon": 252,
        "n_paths": 500,
        "baseline_components": 5,
        "baseline_seed": 0,
        "chronos_seed": 0,
        "w_stress": 0.5305,
        "regime_threshold": 0.7,
        "book_id": "cross_asset_demo_v1",
        "conditioning": None,
        "provenance": deepcopy(PROVENANCE),
        "spec_hash": SPEC_HASH,
        "execution_id": execution_id,
    }


def _exposure(execution_id: str, role: str, hash_character: str) -> dict[str, object]:
    source = {
        "baseline": "parametric",
        "chronos_only": "chronos2",
        "augmented": "blended",
    }[role]
    return {
        "type": "exposure_result",
        "execution_id": execution_id,
        "spec_hash": SPEC_HASH,
        "scenario_role": role,
        "source": source,
        "paths_uri": f"s3://data/runs/{execution_id}/{role}.pkl",
        "paths_sha256": hash_character * 64,
        "metrics_uri": f"s3://data/runs/{execution_id}/metrics/{role}.json",
        "metrics_sha256": hash_character * 64,
        "terminal": {
            "date": "2023-09-19",
            "ee": 100.004,
            "pfe_975": 200.004,
            "es_975": 300.004,
        },
    }


def _diagnostics(execution_id: str) -> dict[str, object]:
    attribution = {
        name: {"terminal": {"ee": 1.0, "pfe_975": 2.0, "es_975": 3.0}}
        for name in (
            "uniform_parametric",
            "uniform_chronos",
            "reweighted_parametric",
            "reweighted_chronos",
            "final_blend",
        )
    }
    portfolio = {
        role: {"coverage": 0.98, "nominal": 0.975}
        for role in ROLES
    }
    factor = {
        role: {
            "coverage": 0.95,
            "nominal": 0.95,
            "per_series": {f"series-{index}": 0.95 for index in range(21)},
        }
        for role in ROLES
    }
    return {
        "type": "diagnostics",
        "execution_id": execution_id,
        "spec_hash": SPEC_HASH,
        "diagnostics_uri": f"s3://data/runs/{execution_id}/diagnostics.json",
        "diagnostics_sha256": "9" * 64,
        "diagnostics": {
            "attribution": attribution,
            "portfolio_coverage": {"available": True, "results": portfolio},
            "factor_coverage": {"available": True, "results": factor},
        },
    }


def _plot(execution_id: str, role: str, hash_character: str) -> dict[str, object]:
    return {
        "type": "tool",
        "tool_use_id": f"{execution_id}-{role}",
        "name": "plot",
        "status": "done",
        "result": {
            "status": "ok",
            "result": {
                "execution_id": execution_id,
                "spec_hash": SPEC_HASH,
                "plot_role": role,
                "image_s3_uri": f"s3://plots/runs/{execution_id}/plots/{role}.png",
                "image_uri": f"https://plots.example/{execution_id}/{role}.png",
                "image_sha256": hash_character * 64,
            },
        },
    }


def recorded_run(index: int) -> list[dict[str, object]]:
    execution_id = f"run-{index}"
    return [
        {
            "type": "run_spec",
            "execution_id": execution_id,
            "spec_hash": SPEC_HASH,
            "run_spec": _run_spec(execution_id),
        },
        _exposure(execution_id, "baseline", "1"),
        _exposure(execution_id, "chronos_only", "2"),
        _exposure(execution_id, "augmented", "3"),
        _diagnostics(execution_id),
        _plot(execution_id, "regime_ribbon", "4"),
        _plot(execution_id, "pfe_overlay", "5"),
        {"type": "done"},
    ]


def recorded_runs() -> list[list[dict[str, object]]]:
    return [recorded_run(index) for index in range(1, 4)]


def test_collect_events_parses_native_multiline_sse(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode):
            assert decode_unicode is True
            return iter([
                ": heartbeat",
                'data: {"type":"text",',
                'data: "text":"hello"}',
                "",
                'data: {"type":"done"}',
                "",
            ])

    def get(url, *, params, headers, stream, timeout):
        assert url == "https://stream.example/"
        assert params["prompt"] == "run"
        assert params["session_id"]
        assert headers == {"x-api-key": "secret"}
        assert stream is True
        assert timeout == (10, 900)
        return Response()

    monkeypatch.setattr(verifier.requests, "get", get)

    assert verifier.collect_events(
        "https://stream.example/", "secret", "run"
    ) == [
        {"type": "text", "text": "hello"},
        {"type": "done"},
    ]


def test_swapped_event_order_passes():
    runs = recorded_runs()
    runs[1] = list(reversed(runs[1]))

    summaries = verifier.verify_runs(runs)

    assert [summary["execution_id"] for summary in summaries] == [
        "run-1", "run-2", "run-3"
    ]


def test_one_cent_metric_difference_fails_with_specific_message():
    runs = recorded_runs()
    runs[1][1]["terminal"]["ee"] = 100.014

    with pytest.raises(
        AssertionError,
        match=r"run 2 baseline\.ee differs: 100\.01 != 100\.00",
    ):
        verifier.verify_runs(runs)


def test_missing_chronos_only_result_fails_with_specific_message():
    runs = recorded_runs()
    runs[1] = [
        event
        for event in runs[1]
        if event.get("scenario_role") != "chronos_only"
    ]

    with pytest.raises(
        AssertionError,
        match=r"exposure roles differ: \['augmented', 'baseline'\]",
    ):
        verifier.verify_runs(runs)


def test_failed_retry_fails_with_specific_message():
    runs = recorded_runs()
    runs[1].append({
        "type": "tool",
        "tool_use_id": "failed-retry",
        "name": "check_chronos2",
        "status": "failed",
        "result": {"status": "error", "message": "retry failed"},
    })

    with pytest.raises(AssertionError, match="failed tool lifecycle events"):
        verifier.verify_runs(runs)


def test_reused_execution_id_fails_with_specific_message():
    runs = recorded_runs()
    for event in runs[1]:
        if "execution_id" in event:
            event["execution_id"] = "run-1"
        if event.get("type") == "run_spec":
            event["run_spec"]["execution_id"] = "run-1"
        result = verifier._tool_result(event)
        if result:
            result["execution_id"] = "run-1"

    with pytest.raises(
        AssertionError,
        match="execution_id values are not distinct",
    ):
        verifier.verify_runs(runs)


def test_provenance_mismatch_fails_with_specific_message():
    runs = recorded_runs()
    runs[1][0]["run_spec"]["provenance"]["agent_image_digest"] = (
        "sha256:" + "0" * 64
    )

    with pytest.raises(AssertionError, match="run provenance differs"):
        verifier.verify_runs(runs)


def test_duplicate_exposure_role_fails_instead_of_overwriting():
    runs = recorded_runs()
    runs[0].append(deepcopy(runs[0][1]))

    with pytest.raises(
        AssertionError,
        match="expected one exposure result for baseline, got 2",
    ):
        verifier.verify_runs(runs)


def test_invalid_exposure_artifact_uri_fails():
    runs = recorded_runs()
    runs[0][1]["paths_uri"] = "https://example/baseline.pkl"

    with pytest.raises(AssertionError, match="baseline paths URI is invalid"):
        verifier.verify_runs(runs)


def test_unpinned_provenance_fails():
    runs = recorded_runs()
    del runs[0][0]["run_spec"]["provenance"]["agent_image_digest"]

    with pytest.raises(AssertionError, match="run provenance is not pinned"):
        verifier.verify_runs(runs)


def test_cli_collects_three_runs_and_writes_raw_and_summary_files(
    monkeypatch,
    tmp_path,
):
    runs = recorded_runs()
    calls = []

    def collect_events(stream_url, api_key, prompt):
        calls.append((stream_url, api_key, prompt))
        return runs[len(calls) - 1]

    monkeypatch.setattr(verifier, "collect_events", collect_events)
    output = tmp_path / "acceptance.json"

    result = verifier.main([
        "--stream-url", "https://stream.example/",
        "--api-key", "secret",
        "--runs", "3",
        "--prompt", verifier.CANONICAL_PROMPT,
        "--output", str(output),
    ])

    assert result == 0
    assert len(calls) == 3
    for index, expected in enumerate(runs, 1):
        raw_path = tmp_path / f"acceptance-run-{index}.events.json"
        assert json.loads(raw_path.read_text()) == expected
    summary = json.loads(output.read_text())
    assert summary["status"] == "passed"
    assert len(summary["runs"]) == 3


def test_cli_rejects_non_three_run_acceptance():
    with pytest.raises(SystemExit, match="--runs must be 3"):
        verifier.main([
            "--stream-url", "https://stream.example/",
            "--api-key", "secret",
            "--runs", "2",
            "--prompt", verifier.CANONICAL_PROMPT,
            "--output", "ignored.json",
        ])
