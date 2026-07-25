from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from chronos2_demo.run_spec import compute_spec_hash
from scripts import verify_live_reproducibility as verifier


ROLES = ("baseline", "chronos_only", "augmented")
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
RUN_SPEC_PAYLOAD = {
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
    "provenance": PROVENANCE,
}
SPEC_HASH = compute_spec_hash(RUN_SPEC_PAYLOAD)
RUNBOOK_PATH = Path(__file__).parents[1] / "docs" / "runbook.md"


def _run_spec(execution_id: str) -> dict[str, object]:
    return {
        **deepcopy(RUN_SPEC_PAYLOAD),
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
        assert timeout[0] == 10
        assert timeout[1] == pytest.approx(900, abs=0.1)
        return Response()

    monkeypatch.setattr(verifier.requests, "get", get)

    assert verifier.collect_events(
        "https://stream.example/", "secret", "run"
    ) == [
        {"type": "text", "text": "hello"},
        {"type": "done"},
    ]


def test_collect_events_accepts_data_field_without_space(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode):
            return iter([
                "event: message",
                "id: 1",
                'data:{"type":"done"}',
                "",
            ])

    monkeypatch.setattr(verifier.requests, "get", lambda *args, **kwargs: Response())

    assert verifier.collect_events("https://stream.example/", "secret", "run") == [
        {"type": "done"}
    ]


def test_collect_events_stops_heartbeat_stream_at_total_deadline(monkeypatch):
    class Response:
        closed = False

        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode):
            while True:
                yield ": heartbeat"

        def close(self):
            self.closed = True

    response = Response()
    monotonic = iter((0.0, 1.0, 2.0, 3.0)).__next__
    monkeypatch.setattr(
        verifier.requests,
        "get",
        lambda *args, **kwargs: response,
    )

    with pytest.raises(
        verifier.SseCollectionDeadlineExceeded,
        match="SSE collection deadline exceeded after 3 seconds",
    ):
        verifier.collect_events(
            "https://stream.example/",
            "secret",
            "run",
            total_deadline_seconds=3,
            monotonic=monotonic,
        )

    assert response.closed is True


def test_collect_events_bounds_blocked_read_at_total_deadline(monkeypatch):
    class Response:
        closed = False

        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode):
            raise verifier.requests.exceptions.ConnectionError("Read timed out.")

        def close(self):
            self.closed = True

    response = Response()
    monotonic = iter((0.0, 0.0, 3.0)).__next__

    def get(*args, timeout, **kwargs):
        assert timeout == (10, 3.0)
        return response

    monkeypatch.setattr(verifier.requests, "get", get)

    with pytest.raises(
        verifier.SseCollectionDeadlineExceeded,
        match="SSE collection deadline exceeded after 3 seconds",
    ):
        verifier.collect_events(
            "https://stream.example/",
            "secret",
            "run",
            total_deadline_seconds=3,
            monotonic=monotonic,
        )

    assert response.closed is True


def test_swapped_event_order_passes():
    runs = recorded_runs()
    runs[1] = [*reversed(runs[1][:-1]), runs[1][-1]]

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
    runs[1].insert(-1, {
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
    changed_hash = compute_spec_hash(runs[1][0]["run_spec"])
    runs[1][0]["run_spec"]["spec_hash"] = changed_hash
    for event in runs[1]:
        if "spec_hash" in event:
            event["spec_hash"] = changed_hash
        result = verifier._tool_result(event)
        if result:
            result["spec_hash"] = changed_hash

    with pytest.raises(AssertionError, match="run provenance differs"):
        verifier.verify_runs(runs)


def test_tampered_run_spec_is_rejected_by_hash_binding():
    runs = recorded_runs()
    runs[0][0]["run_spec"]["w_stress"] = 0.99

    with pytest.raises(
        AssertionError,
        match="spec_hash does not match canonical run_spec",
    ):
        verifier.verify_runs(runs)


@pytest.mark.parametrize("role,source", [
    ("baseline", "chronos2"),
    ("chronos_only", "parametric"),
    ("augmented", "chronos2"),
])
def test_role_source_mismatch_is_rejected(role, source):
    runs = recorded_runs()
    event = next(
        item
        for item in runs[0]
        if item.get("scenario_role") == role
    )
    event["source"] = source

    with pytest.raises(AssertionError, match=f"{role} source is invalid"):
        verifier.verify_runs(runs)


def test_unconditioned_chronos_result_rejects_conditioned_source():
    runs = recorded_runs()
    runs[0][2]["source"] = "chronos2_conditional"

    with pytest.raises(AssertionError, match="chronos_only source is invalid"):
        verifier.verify_runs(runs)


def test_duplicate_exposure_role_fails_instead_of_overwriting():
    runs = recorded_runs()
    runs[0].insert(-1, deepcopy(runs[0][1]))

    with pytest.raises(
        AssertionError,
        match="expected one exposure result for baseline, got 2",
    ):
        verifier.verify_runs(runs)


@pytest.mark.parametrize("uri", [
    "https://example/baseline.pkl",
    "s3://",
    "s3:///baseline.pkl",
    "s3://data",
])
def test_invalid_exposure_artifact_uri_fails(uri):
    runs = recorded_runs()
    runs[0][1]["paths_uri"] = uri

    with pytest.raises(AssertionError, match="baseline paths URI is invalid"):
        verifier.verify_runs(runs)


def test_unpinned_provenance_fails():
    runs = recorded_runs()
    del runs[0][0]["run_spec"]["provenance"]["agent_image_digest"]

    with pytest.raises(AssertionError, match="run provenance is not pinned"):
        verifier.verify_runs(runs)


@pytest.mark.parametrize("event_index,label", [
    (0, "run_spec"),
    (4, "diagnostics"),
])
def test_duplicate_structured_event_is_rejected(event_index, label):
    runs = recorded_runs()
    runs[0].insert(-1, deepcopy(runs[0][event_index]))

    with pytest.raises(AssertionError, match=f"expected one {label} event, got 2"):
        verifier.verify_runs(runs)


def test_missing_done_is_rejected_as_truncated():
    runs = recorded_runs()
    runs[0] = [event for event in runs[0] if event.get("type") != "done"]

    with pytest.raises(AssertionError, match="expected one terminal done event, got 0"):
        verifier.verify_runs(runs)


def test_duplicate_done_is_rejected():
    runs = recorded_runs()
    runs[0].append({"type": "done"})

    with pytest.raises(AssertionError, match="expected one terminal done event, got 2"):
        verifier.verify_runs(runs)


def test_event_after_done_is_rejected():
    runs = recorded_runs()
    runs[0].append({"type": "heartbeat"})

    with pytest.raises(AssertionError, match="events appear after terminal done"):
        verifier.verify_runs(runs)


def _calibration_for(run_index: int = 1) -> dict[str, object]:
    summary = verifier.summarize_run(recorded_run(run_index))
    return {
        "run_spec": _run_spec("calibration-run"),
        "terminal_metrics": deepcopy(summary["terminal"]),
    }


def test_calibration_matches_live_at_cent_precision():
    summary = verifier.summarize_run(recorded_run(1))

    verifier.compare_calibration(summary, _calibration_for())


def test_calibration_one_cent_mismatch_is_rejected():
    summary = verifier.summarize_run(recorded_run(1))
    calibration = _calibration_for()
    calibration["terminal_metrics"]["augmented"]["pfe_975"] = 200.014

    with pytest.raises(
        AssertionError,
        match=r"calibration augmented\.pfe_975 differs: 200\.01 != 200\.00",
    ):
        verifier.compare_calibration(summary, calibration)


def test_cli_collects_three_runs_and_writes_raw_and_summary_files(
    monkeypatch,
    tmp_path,
):
    runs = recorded_runs()
    calls = []

    def collect_events(
        stream_url,
        api_key,
        prompt,
        *,
        total_deadline_seconds,
    ):
        assert total_deadline_seconds == verifier.DEFAULT_COLLECTION_DEADLINE_SECONDS
        calls.append((stream_url, api_key, prompt))
        return runs[len(calls) - 1]

    monkeypatch.setattr(verifier, "collect_events", collect_events)
    output = tmp_path / "acceptance.json"
    calibration = tmp_path / "calibration.json"
    calibration.write_text(json.dumps(_calibration_for()))

    result = verifier.main([
        "--stream-url", "https://stream.example/",
        "--api-key", "secret",
        "--runs", "3",
        "--prompt", verifier.CANONICAL_PROMPT,
        "--output", str(output),
        "--calibration", str(calibration),
    ])

    assert result == 0
    assert len(calls) == 3
    for index, expected in enumerate(runs, 1):
        raw_path = tmp_path / f"acceptance-run-{index}.events.json"
        assert json.loads(raw_path.read_text()) == expected
    summary = json.loads(output.read_text())
    assert summary["status"] == "passed"
    assert len(summary["runs"]) == 3
    attempt_dir = tmp_path / summary["attempt_dir"]
    assert attempt_dir.is_dir()
    assert len(list(attempt_dir.glob("run-*.events.json"))) == 3


def test_failed_verification_atomically_replaces_stale_passed_output(
    monkeypatch,
    tmp_path,
):
    runs = recorded_runs()
    runs[1][1]["terminal"]["ee"] = 100.014
    calls = []

    def collect_events(*args, total_deadline_seconds):
        assert total_deadline_seconds == verifier.DEFAULT_COLLECTION_DEADLINE_SECONDS
        calls.append(args)
        return runs[len(calls) - 1]

    monkeypatch.setattr(verifier, "collect_events", collect_events)
    output = tmp_path / "acceptance.json"
    output.write_text('{"status":"passed"}\n')
    calibration = tmp_path / "calibration.json"
    calibration.write_text(json.dumps(_calibration_for()))

    with pytest.raises(AssertionError, match=r"run 2 baseline\.ee differs"):
        verifier.main([
            "--stream-url", "https://stream.example/",
            "--api-key", "secret",
            "--runs", "3",
            "--prompt", verifier.CANONICAL_PROMPT,
            "--output", str(output),
            "--calibration", str(calibration),
        ])

    failed = json.loads(output.read_text())
    assert failed["status"] == "failed"
    assert "run 2 baseline.ee differs" in failed["error"]
    assert (tmp_path / failed["attempt_dir"]).is_dir()


def test_failed_collection_atomically_replaces_stale_passed_output(
    monkeypatch,
    tmp_path,
):
    def collect_events(*args, total_deadline_seconds):
        assert total_deadline_seconds == verifier.DEFAULT_COLLECTION_DEADLINE_SECONDS
        raise RuntimeError("collection stopped")

    monkeypatch.setattr(verifier, "collect_events", collect_events)
    output = tmp_path / "acceptance.json"
    output.write_text('{"status":"passed"}\n')
    calibration = tmp_path / "calibration.json"
    calibration.write_text(json.dumps(_calibration_for()))

    with pytest.raises(RuntimeError, match="collection stopped"):
        verifier.main([
            "--stream-url", "https://stream.example/",
            "--api-key", "secret",
            "--runs", "3",
            "--prompt", verifier.CANONICAL_PROMPT,
            "--output", str(output),
            "--calibration", str(calibration),
        ])

    failed = json.loads(output.read_text())
    assert failed["status"] == "failed"
    assert failed["error"] == "collection stopped"


def test_cli_deadline_failure_writes_failed_evidence(monkeypatch, tmp_path):
    def collect_events(*args, total_deadline_seconds):
        assert total_deadline_seconds == 3
        raise verifier.SseCollectionDeadlineExceeded(
            "SSE collection deadline exceeded after 3 seconds"
        )

    monkeypatch.setattr(verifier, "collect_events", collect_events)
    output = tmp_path / "acceptance.json"
    calibration = tmp_path / "calibration.json"
    calibration.write_text(json.dumps(_calibration_for()))

    with pytest.raises(
        verifier.SseCollectionDeadlineExceeded,
        match="SSE collection deadline exceeded after 3 seconds",
    ):
        verifier.main([
            "--stream-url", "https://stream.example/",
            "--api-key", "secret",
            "--runs", "3",
            "--prompt", verifier.CANONICAL_PROMPT,
            "--output", str(output),
            "--calibration", str(calibration),
            "--collection-deadline-seconds", "3",
        ])

    failed = json.loads(output.read_text())
    assert failed["status"] == "failed"
    assert failed["error"] == "SSE collection deadline exceeded after 3 seconds"
    assert failed["error_type"] == "SseCollectionDeadlineExceeded"


def test_cli_rejects_non_three_run_acceptance():
    with pytest.raises(SystemExit, match="--runs must be 3"):
        verifier.main([
            "--stream-url", "https://stream.example/",
            "--api-key", "secret",
            "--runs", "2",
            "--prompt", verifier.CANONICAL_PROMPT,
            "--output", "ignored.json",
            "--calibration", "ignored-calibration.json",
        ])


def _task11_runbook() -> str:
    runbook = RUNBOOK_PATH.read_text()
    return runbook[
        runbook.index("## 0. Production reproducibility acceptance"):
        runbook.index("## 1. Deploy infrastructure")
    ]


def test_runbook_builds_only_clean_exported_commit_and_hashes_frontend():
    runbook = _task11_runbook()

    assert 'git diff --quiet "$GIT_SHA" -- "${DEPLOY_INPUTS[@]}"' in runbook
    assert 'git diff --cached --quiet "$GIT_SHA" -- "${DEPLOY_INPUTS[@]}"' in runbook
    assert 'git archive "$GIT_SHA"' in runbook
    assert 'export BUILD_ROOT=' in runbook
    assert '-f "$BUILD_ROOT/tools/fargate/baseline_mc/Dockerfile"' in runbook
    assert '-f "$BUILD_ROOT/tools/fargate/run_chronos2/Dockerfile"' in runbook
    assert '-f "$BUILD_ROOT/agent/runtime/Dockerfile"' in runbook
    assert 'export FRONTEND_SHA256=' in runbook
    assert '"frontend_artifact_sha256":$frontend_sha256' in runbook
    assert runbook.index("false # BLOCKED: approved frontend-auth") < runbook.index(
        "aws ecr get-login-password"
    )


def test_runbook_agentcore_and_amplify_waiters_are_bounded_and_fail_closed():
    runbook = _task11_runbook()

    assert "set -euo pipefail" in runbook
    assert "AGENT_MAX_ATTEMPTS=" in runbook
    assert "agent runtime did not become READY" in runbook
    assert "agent endpoint did not become READY" in runbook
    assert "AMPLIFY_MAX_ATTEMPTS=" in runbook
    assert "Amplify deployment timed out" in runbook
    assert "FAILED|CANCELLED" in runbook
    assert "CALIBRATION_MAX_SECONDS=" in runbook
    assert "timeout=int(os.environ[\"CALIBRATION_MAX_SECONDS\"])" in runbook
    assert "--collection-deadline-seconds 900" in runbook
    assert "remaining live-stream deadline" in runbook


def test_runbook_structurally_asserts_edge_and_executes_calibration_gate():
    runbook = _task11_runbook()

    for required in (
        "aws lambda get-function-url-config",
        'test "$(jq -r .AuthType',
        'test "$(jq -r .InvokeMode',
        "aws lambda get-policy",
        "lambda:InvokeFunctionUrl",
        "lambda:InvokeFunction",
        "aws cloudfront get-distribution-config",
        "CachePolicyId",
        "OriginRequestPolicyId",
        "WebACLId",
        "OriginAccessControlId",
        "SigningBehavior",
        "x-api-key",
        "--connect-timeout 10 --max-time 30",
        "--calibration docs/results/headline_calibration.json",
    ):
        assert required in runbook


def test_runbook_captures_durable_rollback_inputs_and_restores_semantics():
    runbook = _task11_runbook()

    for required in (
        "PREVIOUS_BASELINE_TASK_JSON",
        "PREVIOUS_CHRONOS_TASK_JSON",
        "PREVIOUS_AGENT",
        "PREVIOUS_AGENT_ENDPOINT",
        "PREVIOUS_AMPLIFY_JOB",
        "PREVIOUS_FRONTEND_ARTIFACT",
        "PREVIOUS_FRONTEND_SHA256",
        "get-template",
        "rollback-parameters.json",
        "ROLLBACK_TEMPLATE_BUCKET",
        "ROLLBACK_BUNDLE_URI",
        'aws s3 cp --recursive "$ROLLBACK_ROOT" "$ROLLBACK_BUNDLE_URI"',
        'aws s3 cp --recursive "$ROLLBACK_BUNDLE_URI" "$ROLLBACK_RESTORE_ROOT"',
        "rollback-files.sha256",
        "*.json *.txt *.zip > rollback-files.sha256",
        "--template-url",
        "update-stack",
        "task_definition_semantics",
        "verify_restored_task_definition",
        "baseline-task.semantics.json",
        "chronos-task.semantics.json",
        "baseline-task.image-digests.txt",
        "chronos-task.image-digests.txt",
        "executionRoleArn",
        "taskRoleArn",
        "containerDefinitions",
        "cpu",
        "memory",
        "cmp --silent",
    ):
        assert required in runbook
    assert 'test "$RESTORED_BASELINE_TASK" = "$PREVIOUS_BASELINE_TASK"' not in runbook
    assert 'test "$RESTORED_CHRONOS_TASK" = "$PREVIOUS_CHRONOS_TASK"' not in runbook
