from __future__ import annotations

from copy import deepcopy
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

import pandas as pd
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
REPO_ROOT = Path(__file__).parents[1]
RUNBOOK_PATH = REPO_ROOT / "docs" / "runbook.md"
RELAY_DIR = REPO_ROOT / "tools" / "lambda" / "sse_relay"
RELAY_LOCK_PATH = RELAY_DIR / "package-lock.json"


def _noncooperative_sse_reader() -> None:
    time.sleep(5)


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
        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode):
            while True:
                yield ": heartbeat"

        def close(self):
            return None

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

def test_collect_events_bounds_blocked_read_at_total_deadline(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode):
            raise verifier.requests.exceptions.ConnectionError("Read timed out.")

        def close(self):
            return None

    response = Response()
    monotonic = iter((0.0, 0.0, 3.0)).__next__

    def get(*args, timeout, **kwargs):
        assert timeout == (3.0, 3.0)
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

def test_collect_events_closes_slow_partial_line_at_wall_clock_deadline(
    monkeypatch,
):
    context = multiprocessing.get_context("fork")

    class Response:
        def __init__(self):
            self.partial_line_started = context.Event()

        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode):
            self.partial_line_started.set()
            time.sleep(1)
            if False:
                yield "data: incomplete"

        def close(self):
            return None

    response = Response()
    monkeypatch.setattr(verifier.requests, "get", lambda *args, **kwargs: response)

    started_at = time.monotonic()
    with pytest.raises(
        verifier.SseCollectionDeadlineExceeded,
        match="SSE collection deadline exceeded after 0.05 seconds",
    ):
        verifier.collect_events(
            "https://stream.example/",
            "secret",
            "run",
            total_deadline_seconds=0.05,
        )
    elapsed_seconds = time.monotonic() - started_at

    assert response.partial_line_started.is_set()
    assert elapsed_seconds < 0.25


def test_collect_events_reaps_noncooperative_reader_at_deadline(monkeypatch):
    context = multiprocessing.get_context("fork")
    started = context.Event()

    class Response:
        reader_ident = None

        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode):
            self.reader_ident = threading.get_ident()
            started.set()
            time.sleep(5)
            if False:
                yield "data: incomplete"

        def close(self):
            return None

    response = Response()
    monkeypatch.setattr(verifier.requests, "get", lambda *args, **kwargs: response)
    stopped_readers = []
    stop_reader = verifier._stop_sse_reader

    def record_stopped_reader(reader):
        stop_reader(reader)
        stopped_readers.append(reader)

    monkeypatch.setattr(verifier, "_stop_sse_reader", record_stopped_reader)

    with pytest.raises(
        verifier.SseCollectionDeadlineExceeded,
        match="SSE collection deadline exceeded after 0.2 seconds",
    ):
        verifier.collect_events(
            "https://stream.example/",
            "secret",
            "run",
            total_deadline_seconds=0.2,
        )

    assert started.wait(timeout=0.5)
    assert response.reader_ident is None
    assert len(stopped_readers) == 1
    assert not stopped_readers[0].is_alive()


def test_stop_sse_reader_reaps_noncooperative_process():
    context = multiprocessing.get_context("fork")
    reader = context.Process(target=_noncooperative_sse_reader)
    reader.start()

    verifier._stop_sse_reader(reader)

    assert not reader.is_alive()


def test_collect_events_allows_completed_reader_to_close(monkeypatch):
    context = multiprocessing.get_context("fork")
    closed = context.Event()

    class Response:
        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode):
            return iter(['data: {"type":"done"}', ""])

        def close(self):
            time.sleep(0.05)
            closed.set()

    monkeypatch.setattr(verifier.requests, "get", lambda *args, **kwargs: Response())

    assert verifier.collect_events("https://stream.example/", "secret", "run") == [
        {"type": "done"}
    ]
    assert closed.wait(timeout=0.2)


def test_clean_archive_rehearsal_stages_inputs_and_installs_relay_hermetically(tmp_path):
    build_root = tmp_path / "build"
    for relative_path in (
        "docs/runbook.md",
        "docs/demo/demo-first-presenter-script.md",
        "tools/lambda/sse_relay/package.json",
        "tools/lambda/sse_relay/package-lock.json",
        "tools/lambda/sse_relay/protocol.test.mjs",
        "tests/test_demo_stage_parameters.py",
        "tests/fixtures/headline_panel.parquet",
        "data/sample_book.json",
    ):
        source = REPO_ROOT / relative_path
        destination = build_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    shutil.copytree(
        REPO_ROOT / "src",
        build_root / "src",
        ignore=shutil.ignore_patterns("__pycache__"),
    )

    assert not (build_root / ".git").exists()
    assert not (build_root / "data" / "curated").exists()
    assert not (build_root / "tools" / "lambda" / "sse_relay" / "node_modules").exists()
    assert (build_root / "tools" / "lambda" / "sse_relay" / "package-lock.json").is_file()

    fake_s3 = tmp_path / "fake-s3"
    fake_s3.mkdir()
    shutil.copy2(
        build_root / "tests" / "fixtures" / "headline_panel.parquet",
        fake_s3 / "panel.parquet",
    )
    pd.DataFrame({"VIX": [20.0]}).to_parquet(fake_s3 / "covariates.parquet")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "aws").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ \"$1 $2\" == 'cloudformation describe-stack-resources' ]]; then\n"
        "  printf 'fixture-bucket\\n'\n"
        "elif [[ \"$1 $2\" == 's3 cp' ]]; then\n"
        "  cp \"$FAKE_S3/$(basename \"$3\")\" \"$4\"\n"
        "else\n"
        "  printf 'unexpected aws call: %s\\n' \"$*\" >&2; exit 1\n"
        "fi\n"
    )
    (fake_bin / "npm").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$*\" >> \"$NPM_LOG\"\n"
    )
    (fake_bin / "node").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$*\" >> \"$NODE_LOG\"\n"
    )
    for command in ("aws", "npm", "node"):
        (fake_bin / command).chmod(0o755)
    archive_runbook = (build_root / "docs" / "runbook.md").read_text()
    function_start = archive_runbook.index("stage_verified_curated_inputs() {")
    function_end = archive_runbook.index("\n}\nstage_verified_curated_inputs", function_start) + 2
    stage_script = archive_runbook[function_start:function_end] + "\nstage_verified_curated_inputs\n"
    relay_matrix_start = archive_runbook.index('cd "$BUILD_ROOT/tools/lambda/sse_relay"')
    relay_matrix_end = archive_runbook.index("\n  )", relay_matrix_start)
    relay_matrix = archive_runbook[relay_matrix_start:relay_matrix_end]
    assert relay_matrix.index("npm ci") < relay_matrix.index("node --test protocol.test.mjs")
    npm_log = tmp_path / "npm.log"
    node_log = tmp_path / "node.log"
    env = {
        **os.environ,
        "BUILD_ROOT": str(build_root),
        "FAKE_S3": str(fake_s3),
        "NPM_LOG": str(npm_log),
        "NODE_LOG": str(node_log),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "PYTHONPATH": str(build_root / "src"),
    }
    subprocess.run(["bash", "-c", stage_script], env=env, check=True)
    assert (build_root / "data" / "curated" / "panel.parquet").is_file()
    assert (build_root / "data" / "curated" / "covariates.parquet").is_file()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_demo_stage_parameters.py",
        ],
        cwd=build_root,
        env=env,
        check=True,
    )
    subprocess.run(
        ["npm", "ci"],
        cwd=build_root / "tools" / "lambda" / "sse_relay",
        env=env,
        check=True,
    )
    subprocess.run(
        ["node", "--test", "protocol.test.mjs"],
        cwd=build_root / "tools" / "lambda" / "sse_relay",
        env=env,
        check=True,
    )
    assert npm_log.read_text() == "ci\n"
    assert node_log.read_text() == "--test protocol.test.mjs\n"


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
    monkeypatch.setenv("CHRONOS2_VERIFY_TEST_KEY", "secret")
    output = tmp_path / "acceptance.json"
    calibration = tmp_path / "calibration.json"
    calibration.write_text(json.dumps(_calibration_for()))

    result = verifier.main([
        "--stream-url", "https://stream.example/",
        "--api-key-env", "CHRONOS2_VERIFY_TEST_KEY",
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
    monkeypatch.setenv("CHRONOS2_VERIFY_TEST_KEY", "secret")
    output = tmp_path / "acceptance.json"
    output.write_text('{"status":"passed"}\n')
    calibration = tmp_path / "calibration.json"
    calibration.write_text(json.dumps(_calibration_for()))

    with pytest.raises(AssertionError, match=r"run 2 baseline\.ee differs"):
        verifier.main([
            "--stream-url", "https://stream.example/",
            "--api-key-env", "CHRONOS2_VERIFY_TEST_KEY",
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
    monkeypatch.setenv("CHRONOS2_VERIFY_TEST_KEY", "secret")
    output = tmp_path / "acceptance.json"
    output.write_text('{"status":"passed"}\n')
    calibration = tmp_path / "calibration.json"
    calibration.write_text(json.dumps(_calibration_for()))

    with pytest.raises(RuntimeError, match="collection stopped"):
        verifier.main([
            "--stream-url", "https://stream.example/",
            "--api-key-env", "CHRONOS2_VERIFY_TEST_KEY",
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
    monkeypatch.setenv("CHRONOS2_VERIFY_TEST_KEY", "secret")
    output = tmp_path / "acceptance.json"
    calibration = tmp_path / "calibration.json"
    calibration.write_text(json.dumps(_calibration_for()))

    with pytest.raises(
        verifier.SseCollectionDeadlineExceeded,
        match="SSE collection deadline exceeded after 3 seconds",
    ):
        verifier.main([
            "--stream-url", "https://stream.example/",
            "--api-key-env", "CHRONOS2_VERIFY_TEST_KEY",
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
            "--api-key-env", "UNUSED_API_KEY",
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
    pre_ecr_acceptance = runbook[:runbook.index("aws ecr get-login-password")]
    assert "false # BLOCKED: approved frontend-auth" not in pre_ecr_acceptance


def test_runbook_stages_verified_sources_before_clean_archive_matrix():
    runbook = _task11_runbook()
    assert "stage_verified_curated_inputs()" in runbook
    matrix_start = runbook.index("Run the complete matrix against the exported commit")
    stage_start = runbook.index("stage_verified_curated_inputs()")
    stage_end = runbook.index("stage_verified_curated_inputs", stage_start + 1)
    stage = runbook[stage_start:stage_end]
    matrix = runbook[matrix_start:]

    assert stage_start < matrix_start
    assert '"s3://$DATA_BUCKET/panel.parquet"' in stage
    assert '"s3://$DATA_BUCKET/covariates.parquet"' in stage
    assert "regimes.parquet" not in stage
    assert 'cd "$BUILD_ROOT/tools/lambda/sse_relay"' in matrix
    assert "npm ci" in matrix
    assert matrix.index("npm ci") < matrix.index("node --test protocol.test.mjs")


def test_relay_lockfile_matches_tracked_dependencies():
    assert RELAY_LOCK_PATH.is_file()
    lock = json.loads(RELAY_LOCK_PATH.read_text())
    package = json.loads((RELAY_DIR / "package.json").read_text())

    assert lock["packages"][""]["dependencies"] == package["dependencies"]


def test_task11_runbook_honors_an_externally_supplied_aws_profile():
    runbook = _task11_runbook()

    assert 'export AWS_PROFILE="${AWS_PROFILE:-default}"' in runbook
    assert "export AWS_PROFILE=chronos2-demo" not in runbook


def test_runbook_updates_the_access_code_and_checks_both_endpoints():
    runbook = _task11_runbook()
    rotation = runbook[
        runbook.index("### 0e. API key rotation acceptance"):
        runbook.index("### 0f. Streaming-edge and live stop gates")
    ]

    assert "aws secretsmanager rotate-secret" not in rotation
    assert "openssl rand -hex 32" in rotation
    assert "aws secretsmanager put-secret-value" in rotation
    assert 'file:///dev/stdin' in rotation
    assert '--secret-string "$NEW_API_KEY"' not in rotation
    assert 'secret_string "$NEW_API_KEY"' not in rotation
    assert "python3 -c" in rotation
    assert "PREVIOUS_API_KEY_VERSION_ID" in rotation
    assert "NEW_API_KEY_VERSION_ID" in rotation
    assert "ClientRequestToken" in rotation
    assert "VersionStages" in rotation
    assert "TASK11_CANDIDATE" in rotation
    assert "update-secret-version-stage" in rotation
    assert "trap restore_previous_api_key EXIT" in rotation
    assert "trap - EXIT" in rotation
    assert "curl_with_api_key()" in rotation
    assert rotation.count('curl_with_api_key "$OLD_API_KEY"') == 2
    assert rotation.count('curl_with_api_key "$NEW_API_KEY"') == 2
    assert '-H "x-api-key:' not in rotation
    assert "--config -" in rotation
    assert rotation.count("--connect-timeout 10 --max-time 30") == 4
    assert "current_api_key_version_id=$(aws secretsmanager get-secret-value" not in rotation
    assert 'echo "$OLD_API_KEY"' not in rotation
    assert 'echo "$NEW_API_KEY"' not in rotation


def test_runbook_live_verifier_reads_its_access_code_from_a_named_environment():
    runbook = _task11_runbook()
    verifier_start = runbook.index("scripts/verify_live_reproducibility.py")
    verifier_call = runbook[
        runbook.rindex("CHRONOS2_VERIFY_API_KEY", 0, verifier_start):
        runbook.index('test "$(jq -r .status', verifier_start)
    ]

    assert "--api-key \"$API_KEY\"" not in verifier_call
    assert "--api-key-env CHRONOS2_VERIFY_API_KEY" in verifier_call
    assert 'CHRONOS2_VERIFY_API_KEY="$API_KEY"' in verifier_call
    assert 'x-api-key: $' not in runbook
    assert 'add_argument("--api-key"' not in Path(verifier.__file__).read_text()


def _rotation_acceptance_script() -> str:
    runbook = _task11_runbook()
    rotation = runbook[
        runbook.index("### 0e. API key rotation acceptance"):
        runbook.index("### 0f. Streaming-edge and live stop gates")
    ]
    start = rotation.index("```bash\n") + len("```bash\n")
    return rotation[start:rotation.index("\n```", start)]


def _run_rotation_rehearsal(tmp_path, failure_mode: str | None) -> tuple[subprocess.CompletedProcess[str], str, str]:
    state = tmp_path / "current-version"
    state.write_text("old-version\n")
    log = tmp_path / "calls.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "aws").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf 'AWS_ARGV:%s\\n' \"$*\" >> \"$CALL_LOG\"\n"
        "case \"$1 $2\" in\n"
        "  'apigateway get-authorizers') printf 'authorizer-id\\n' ;;\n"
        "  'apigateway update-authorizer') ;;\n"
        "  'apigateway get-authorizer') printf '0\\n' ;;\n"
        "  'secretsmanager get-secret-value')\n"
        "    if [[ \"$*\" == *'VersionId'* ]]; then cat \"$CURRENT_VERSION\"; else printf 'old-secret\\n'; fi ;;\n"
        "  'secretsmanager put-secret-value')\n"
        "    cat > \"$PUT_INPUT\"\n"
        "    grep -q '\"ClientRequestToken\": \"new-version\"' \"$PUT_INPUT\"\n"
        "    grep -q '\"VersionStages\": \\[\"TASK11_CANDIDATE_new-version\"\\]' \"$PUT_INPUT\"\n"
        "    if [[ \"$FAILURE_MODE\" == candidate-response-lost ]]; then exit 1; fi ;;\n"
        "  'secretsmanager update-secret-version-stage')\n"
        "    if [[ \"$*\" == *'--move-to-version-id new-version --remove-from-version-id old-version'* ]]; then\n"
        "      printf 'new-version\\n' > \"$CURRENT_VERSION\"\n"
        "      if [[ \"$FAILURE_MODE\" == promotion-response-lost || \"$FAILURE_MODE\" == cleanup-fails ]]; then exit 1; fi\n"
        "    elif [[ \"$*\" == *'--move-to-version-id old-version --remove-from-version-id new-version'* ]]; then\n"
        "      if [[ \"$FAILURE_MODE\" == cleanup-fails ]]; then exit 1; fi\n"
        "      printf 'old-version\\n' > \"$CURRENT_VERSION\"\n"
        "    else\n"
        "      printf 'unexpected stage update: %s\\n' \"$*\" >&2; exit 1\n"
        "    fi ;;\n"
        "  *) printf 'unexpected aws call: %s\\n' \"$*\" >&2; exit 1 ;;\n"
        "esac\n"
    )
    (fake_bin / "curl").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf 'CURL_ARGV:%s\\n' \"$*\" >> \"$CALL_LOG\"\n"
        "config=$(cat)\n"
        "printf 'CURL_CONFIG:%s\\n' \"$config\" >> \"$CALL_LOG\"\n"
        "if [[ \"$*\" == *'/sessions'* && \"$config\" == *old-secret* ]]; then\n"
        "  printf '401'\n"
        "elif [[ \"$*\" == *'/sessions'* && \"$config\" == *new-secret* ]]; then\n"
        "  printf '{\\\"session_id\\\":\\\"new-session\\\"}'\n"
        "elif [[ \"$*\" == *rotation-check* && \"$config\" == *old-secret* ]]; then\n"
        "  printf '403'\n"
        "elif [[ \"$*\" == *rotation-check* && \"$config\" == *new-secret* ]]; then\n"
        "  printf '200'\n"
        "else\n"
        "  printf 'unexpected curl call: %s' \"$*\" >&2; exit 1\n"
        "fi\n"
    )
    (fake_bin / "openssl").write_text(
        "#!/usr/bin/env bash\n"
        "printf 'new-secret\\n'\n"
    )
    (fake_bin / "python3").write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$2\" == *'uuid.uuid4'* ]]; then printf 'new-version\\n'; else exec \"$REAL_PYTHON\" \"$@\"; fi\n"
    )
    for command in ("aws", "curl", "openssl", "python3"):
        (fake_bin / command).chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + _rotation_acceptance_script()],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "API_URL": "https://api.example/",
            "STREAM_URL": "https://stream.example/",
            "API_KEY_SECRET_ARN": "secret-arn",
            "CURRENT_VERSION": str(state),
            "CALL_LOG": str(log),
            "PUT_INPUT": str(tmp_path / "put-input.json"),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "FAILURE_MODE": failure_mode or "",
            "REAL_PYTHON": sys.executable,
        },
    )
    return result, state.read_text(), log.read_text()


def test_rotation_rehearsal_keeps_access_codes_out_of_child_argv(tmp_path):
    result, current_version, log = _run_rotation_rehearsal(tmp_path, None)

    assert result.returncode == 0, result.stderr
    assert current_version == "new-version\n"
    curl_argv = [line for line in log.splitlines() if line.startswith("CURL_ARGV:")]
    assert len(curl_argv) == 4
    assert all("old-secret" not in line and "new-secret" not in line for line in curl_argv)
    assert all("--config -" in line for line in curl_argv)


def test_rotation_rehearsal_restores_previous_version_after_lost_promotion_response(tmp_path):
    result, current_version, log = _run_rotation_rehearsal(
        tmp_path, "promotion-response-lost"
    )

    assert result.returncode != 0
    assert current_version == "old-version\n"
    assert (
        "update-secret-version-stage --secret-id secret-arn --version-stage AWSCURRENT "
        "--move-to-version-id old-version --remove-from-version-id new-version"
    ) in log


def test_rotation_rehearsal_keeps_awscurrent_after_a_stale_lost_candidate_write(tmp_path):
    result, current_version, log = _run_rotation_rehearsal(
        tmp_path, "candidate-response-lost"
    )

    assert result.returncode != 0
    assert current_version == "old-version\n"
    assert "update-secret-version-stage" not in log


def test_rotation_rehearsal_fails_closed_when_exact_cleanup_fails(tmp_path):
    result, current_version, log = _run_rotation_rehearsal(
        tmp_path, "cleanup-fails"
    )

    assert result.returncode != 0
    assert current_version == "new-version\n"
    assert "API key cleanup failed; AWSCURRENT may not be restored" in result.stderr
    assert (
        "update-secret-version-stage --secret-id secret-arn --version-stage AWSCURRENT "
        "--move-to-version-id old-version --remove-from-version-id new-version"
    ) in log


def test_runbook_stages_canonical_curated_data_before_hashing_it():
    runbook = _task11_runbook()
    provenance = runbook[
        runbook.index("### 0c. Pin data and deployment provenance"):
        runbook.index("### 0d. Deploy in dependency-safe order")
    ]

    assert "stage_verified_curated_inputs" in provenance
    assert "regimes.parquet" not in provenance
    assert 'export MARKET_SNAPSHOT_ID="panel.parquet@sha256:${MARKET_SHA256}"' in provenance
    assert (
        'export COVARIATE_SNAPSHOT_ID='
        '"covariates.parquet@sha256:${COVARIATE_SHA256}"'
    ) in provenance
    assert 'export MARKET_SNAPSHOT_ID="panel.parquet@${GIT_SHA}"' not in provenance
    assert 'export COVARIATE_SNAPSHOT_ID="covariates.parquet@${GIT_SHA}"' not in provenance


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
    assert (
        '[.job.steps[] | select(.stepName=="DEPLOY") | .artifactsUrl '
        '| select(length > 0)] | last // empty'
    ) in runbook
    assert "[.job.steps[]?.artifactsUrl | select(length > 0)] | last // empty" not in runbook


def _restore_stack_function() -> str:
    runbook = _task11_runbook()
    start = runbook.index("restore_stack() {")
    end = runbook.index("\n}\n\nverify_restored_task_definition", start) + 2
    return runbook[start:end]


def _run_restore_stack_rehearsal(tmp_path, current_template: dict[str, object]) -> str:
    rollback_root = tmp_path / "rollback"
    rollback_root.mkdir(parents=True)
    captured_template = {"Resources": {"Example": {"Type": "AWS::S3::Bucket"}}}
    parameters = [{"ParameterKey": "ImageTag", "ParameterValue": "captured"}]
    (rollback_root / "Chronos2DemoTools.template.json").write_text(
        json.dumps(captured_template)
    )
    (rollback_root / "Chronos2DemoTools.rollback-parameters.json").write_text(
        json.dumps(parameters)
    )
    current_template_path = tmp_path / "current-template.json"
    current_template_path.write_text(json.dumps(current_template))
    current_stack_path = tmp_path / "current-stack.json"
    current_stack_path.write_text(json.dumps({"Stacks": [{"Parameters": parameters}]}))
    aws_log = tmp_path / "aws.log"
    aws = tmp_path / "aws"
    aws.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "case \"$*\" in\n"
        "  *'cloudformation get-template'*) cat \"$CURRENT_TEMPLATE\" ;;\n"
        "  *'cloudformation describe-stacks'*'StackStatus'*) printf 'UPDATE_COMPLETE\\n' ;;\n"
        "  *'cloudformation describe-stacks'*) cat \"$CURRENT_STACK\" ;;\n"
        "  *'cloudformation update-stack'*) printf 'update\\n' >> \"$AWS_LOG\" ;;\n"
        "  *'cloudformation wait stack-update-complete'*) printf 'wait\\n' >> \"$AWS_LOG\" ;;\n"
        "  *'s3 cp'*) printf 'copy\\n' >> \"$AWS_LOG\" ;;\n"
        "  *) printf 'unexpected aws call: %s\\n' \"$*\" >&2; exit 1 ;;\n"
        "esac\n"
    )
    aws.chmod(0o755)
    script = "\n".join((
        "set -euo pipefail",
        _restore_stack_function(),
        "restore_stack Chronos2DemoTools",
    ))
    result = subprocess.run(
        ["bash", "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "AWS_LOG": str(aws_log),
            "CURRENT_TEMPLATE": str(current_template_path),
            "CURRENT_STACK": str(current_stack_path),
            "ROLLBACK_ROOT": str(rollback_root),
            "ROLLBACK_BUNDLE_PREFIX": "rollback-prefix",
            "ROLLBACK_TEMPLATE_BUCKET": "rollback-bucket",
            "AWS_REGION": "us-east-1",
        },
    )
    return aws_log.read_text() if aws_log.exists() else result.stdout


def test_runbook_restore_stack_skips_equal_inputs_and_updates_changed_inputs(tmp_path):
    captured_template = {"Resources": {"Example": {"Type": "AWS::S3::Bucket"}}}

    no_op_log = _run_restore_stack_rehearsal(tmp_path / "no-op", captured_template)
    changed_log = _run_restore_stack_rehearsal(
        tmp_path / "changed",
        {"Resources": {"Example": {"Type": "AWS::SNS::Topic"}}},
    )

    assert "update" not in no_op_log
    assert "wait" not in no_op_log
    assert "update" in changed_log
    assert "wait" in changed_log
