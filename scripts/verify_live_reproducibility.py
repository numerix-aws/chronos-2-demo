"""Verify three independent live quantitative runs under pinned provenance."""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import re
import uuid

import requests

from chronos2_demo.run_spec import Clarification, compile_run_spec


ROLES = ("baseline", "chronos_only", "augmented")
METRICS = ("ee", "pfe_975", "es_975")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
IMAGE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
GIT_VERSION_RE = re.compile(r"^git:[0-9a-f]{7,40}$")
PROVENANCE_KEYS = {
    "market_snapshot_id",
    "market_sha256",
    "covariate_snapshot_id",
    "covariate_sha256",
    "chronos_endpoint",
    "chronos_model_version",
    "baseline_image_digest",
    "chronos_image_digest",
    "agent_image_digest",
    "book_version",
    "blend_version",
    "pricing_version",
    "tool_bundle_version",
    "strands_version",
}
CANONICAL_PROMPT = (
    "Run the stage-safe headline demo for September 30, 2022. Use five years "
    "of trading history, project one trading year into the future, and generate "
    "500 scenarios with each engine. Apply a 53.05% stress weight. Show the "
    "market regime and compare baseline exposure with Chronos-2-augmented "
    "exposure. Report the final EE, 97.5% PFE, 97.5% ES, and the PFE change."
)
WORDING_VARIANTS = (
    "As of 2022-09-30, use 1,260 trading days of history, simulate 252 trading "
    "days ahead with 500 paths per engine, and use a 0.5305 stress weight. "
    "Compare baseline and Chronos-2-augmented exposure.",
    "Run the stage safe comparison on Sep 30 2022 with five trading years behind "
    "us and one trading year forward, 500 scenarios from each model, and 53.05 "
    "percent stress weighting.",
)
LOCAL_PROVENANCE = {
    "market_snapshot_id": "local-market",
    "market_sha256": "a" * 64,
    "covariate_snapshot_id": "local-covariates",
    "covariate_sha256": "b" * 64,
    "chronos_endpoint": "local-endpoint",
    "chronos_model_version": "chronos-2",
    "baseline_image_digest": "sha256:" + "c" * 64,
    "chronos_image_digest": "sha256:" + "d" * 64,
    "agent_image_digest": "sha256:" + "e" * 64,
    "book_version": "cross_asset_demo_v1",
    "blend_version": "importance_weight_v1",
    "pricing_version": "cross_asset_v1",
    "tool_bundle_version": "git:0000000",
    "strands_version": "1.30.0",
}


def collect_events(
    stream_url: str,
    api_key: str,
    prompt: str,
) -> list[dict[str, object]]:
    response = requests.get(
        stream_url,
        params={"session_id": str(uuid.uuid4()), "prompt": prompt},
        headers={"x-api-key": api_key},
        stream=True,
        timeout=(10, 900),
    )
    response.raise_for_status()
    events: list[dict[str, object]] = []
    data_lines: list[str] = []
    for line in response.iter_lines(decode_unicode=True):
        if line == "":
            if data_lines:
                events.append(json.loads("\n".join(data_lines)))
                data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data: "):
            data_lines.append(line[6:])
    if data_lines:
        events.append(json.loads("\n".join(data_lines)))
    return events


def _cent(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _is_hash(value: object) -> bool:
    return bool(HASH_RE.fullmatch(str(value)))


def _tool_result(event: dict[str, object]) -> dict[str, object] | None:
    if event.get("type") != "tool" or event.get("status") != "done":
        return None
    envelope = event.get("result")
    if not isinstance(envelope, dict) or envelope.get("status") != "ok":
        return None
    result = envelope.get("result")
    return result if isinstance(result, dict) else None


def _validate_provenance(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != PROVENANCE_KEYS:
        raise AssertionError("run provenance is not pinned")
    if any(not isinstance(item, str) or not item for item in value.values()):
        raise AssertionError("run provenance is not pinned")
    if not _is_hash(value["market_sha256"]) or not _is_hash(
        value["covariate_sha256"]
    ):
        raise AssertionError("run provenance is not pinned")
    for name in (
        "baseline_image_digest",
        "chronos_image_digest",
        "agent_image_digest",
    ):
        if not IMAGE_DIGEST_RE.fullmatch(value[name]):
            raise AssertionError("run provenance is not pinned")
    if not GIT_VERSION_RE.fullmatch(value["tool_bundle_version"]):
        raise AssertionError("run provenance is not pinned")
    return value


def _validate_artifact(
    event: dict[str, object],
    *,
    role: str,
    uri_name: str,
    hash_name: str,
    label: str,
) -> None:
    if not str(event.get(uri_name, "")).startswith("s3://"):
        raise AssertionError(f"{role} {label} URI is invalid")
    if not _is_hash(event.get(hash_name)):
        raise AssertionError(f"{role} {label} hash is invalid")


def summarize_run(events: list[dict[str, object]]) -> dict[str, object]:
    stream_errors = [event for event in events if event.get("type") == "error"]
    if stream_errors:
        raise AssertionError(f"stream errors: {stream_errors}")
    failures = [
        event
        for event in events
        if event.get("type") == "tool" and event.get("status") == "failed"
    ]
    if failures:
        raise AssertionError(f"failed tool lifecycle events: {failures}")

    specs = [event for event in events if event.get("type") == "run_spec"]
    if len(specs) != 1:
        raise AssertionError(f"expected one run_spec event, got {len(specs)}")
    spec_event = specs[0]
    run_spec = spec_event.get("run_spec")
    if not isinstance(run_spec, dict):
        raise AssertionError("run_spec payload is not an object")
    execution_id = str(spec_event.get("execution_id", ""))
    spec_hash = str(spec_event.get("spec_hash", ""))
    if (
        not execution_id
        or run_spec.get("execution_id") != execution_id
        or run_spec.get("spec_hash") != spec_hash
        or not _is_hash(spec_hash)
    ):
        raise AssertionError("run_spec identity is invalid")
    _validate_provenance(run_spec.get("provenance"))

    exposure_events = [
        event for event in events if event.get("type") == "exposure_result"
    ]
    observed_roles = {str(event.get("scenario_role")) for event in exposure_events}
    if observed_roles != set(ROLES):
        raise AssertionError(f"exposure roles differ: {sorted(observed_roles)}")
    exposures: dict[str, dict[str, object]] = {}
    for role in ROLES:
        matches = [
            event
            for event in exposure_events
            if event.get("scenario_role") == role
        ]
        if len(matches) != 1:
            raise AssertionError(
                f"expected one exposure result for {role}, got {len(matches)}"
            )
        event = matches[0]
        if (
            event.get("execution_id") != execution_id
            or event.get("spec_hash") != spec_hash
        ):
            raise AssertionError(f"{role} exposure identity is invalid")
        _validate_artifact(
            event,
            role=role,
            uri_name="paths_uri",
            hash_name="paths_sha256",
            label="paths",
        )
        _validate_artifact(
            event,
            role=role,
            uri_name="metrics_uri",
            hash_name="metrics_sha256",
            label="metrics",
        )
        terminal = event.get("terminal")
        if not isinstance(terminal, dict) or not all(
            metric in terminal for metric in METRICS
        ):
            raise AssertionError(f"{role} terminal metrics are invalid")
        exposures[role] = event

    diagnostics = [event for event in events if event.get("type") == "diagnostics"]
    if len(diagnostics) != 1:
        raise AssertionError(f"expected one diagnostics event, got {len(diagnostics)}")
    diagnostic_event = diagnostics[0]
    if (
        diagnostic_event.get("execution_id") != execution_id
        or diagnostic_event.get("spec_hash") != spec_hash
    ):
        raise AssertionError("diagnostics identity is invalid")
    _validate_artifact(
        diagnostic_event,
        role="diagnostics",
        uri_name="diagnostics_uri",
        hash_name="diagnostics_sha256",
        label="artifact",
    )
    diagnostic_body = diagnostic_event.get("diagnostics")
    if not isinstance(diagnostic_body, dict):
        raise AssertionError("diagnostics payload is not an object")
    attribution = diagnostic_body.get("attribution")
    expected_distributions = {
        "uniform_parametric",
        "uniform_chronos",
        "reweighted_parametric",
        "reweighted_chronos",
        "final_blend",
    }
    if not isinstance(attribution, dict) or set(attribution) != expected_distributions:
        raise AssertionError("attribution does not contain all five distributions")
    for coverage_name in ("portfolio_coverage", "factor_coverage"):
        coverage = diagnostic_body.get(coverage_name)
        if not isinstance(coverage, dict) or coverage.get("available") is not True:
            raise AssertionError(f"{coverage_name} is unavailable")
        if set(coverage.get("results", {})) != set(ROLES):
            raise AssertionError(
                f"{coverage_name} does not contain all three roles"
            )
    factor_results = diagnostic_body["factor_coverage"]["results"]
    for role in ROLES:
        if len(factor_results[role].get("per_series", {})) != 21:
            raise AssertionError(
                f"factor_coverage for {role} does not contain 21 series"
            )

    plot_results: dict[str, list[dict[str, object]]] = {
        "regime_ribbon": [],
        "pfe_overlay": [],
    }
    for event in events:
        if event.get("name") != "plot":
            continue
        result = _tool_result(event)
        if result and result.get("plot_role") in plot_results:
            plot_results[str(result["plot_role"])].append(result)
    observed_plots = {
        role for role, values in plot_results.items() if values
    }
    if observed_plots != set(plot_results):
        raise AssertionError(f"plot roles differ: {sorted(observed_plots)}")
    plots: dict[str, dict[str, object]] = {}
    for role, results in plot_results.items():
        if len(results) != 1:
            raise AssertionError(
                f"expected one successful {role} plot, got {len(results)}"
            )
        result = results[0]
        if (
            result.get("execution_id") != execution_id
            or result.get("spec_hash") != spec_hash
        ):
            raise AssertionError(f"{role} plot identity is invalid")
        if not _is_hash(result.get("image_sha256")):
            raise AssertionError(f"{role} image hash is invalid")
        if not str(result.get("image_s3_uri", "")).startswith("s3://"):
            raise AssertionError(f"{role} stable image URI is invalid")
        if not str(result.get("image_uri", "")).startswith("https://"):
            raise AssertionError(f"{role} browser image URI is not HTTPS")
        plots[role] = result

    return {
        "execution_id": execution_id,
        "spec_hash": spec_hash,
        "run_spec": run_spec,
        "terminal": {
            role: {
                metric: exposures[role]["terminal"][metric]
                for metric in METRICS
            }
            for role in ROLES
        },
        "diagnostics": diagnostic_body,
        "plots": plots,
    }


def verify_runs(
    event_runs: list[list[dict[str, object]]],
) -> list[dict[str, object]]:
    if len(event_runs) != 3:
        raise AssertionError(
            f"expected three independent runs, got {len(event_runs)}"
        )
    summaries = [summarize_run(events) for events in event_runs]
    execution_ids = {str(item["execution_id"]) for item in summaries}
    if len(execution_ids) != 3:
        raise AssertionError("execution_id values are not distinct")
    spec_hashes = {str(item["spec_hash"]) for item in summaries}
    if len(spec_hashes) != 1:
        raise AssertionError("spec_hash values differ")
    provenance = [item["run_spec"]["provenance"] for item in summaries]
    if provenance[1:] != provenance[:-1]:
        raise AssertionError("run provenance differs")
    canonical_specs = []
    for item in summaries:
        canonical = dict(item["run_spec"])
        canonical.pop("execution_id", None)
        canonical.pop("spec_hash", None)
        canonical_specs.append(canonical)
    if canonical_specs[1:] != canonical_specs[:-1]:
        raise AssertionError("canonical RunSpec values differ")
    reference = summaries[0]["terminal"]
    for index, summary in enumerate(summaries[1:], start=2):
        for role in ROLES:
            for metric in METRICS:
                expected = _cent(reference[role][metric])
                actual = _cent(summary["terminal"][role][metric])
                if actual != expected:
                    raise AssertionError(
                        f"run {index} {role}.{metric} differs: "
                        f"{actual} != {expected}"
                    )
    return summaries


def verify_local_wording_variants(prompt: str) -> str:
    specs = [
        compile_run_spec(
            value,
            provenance=LOCAL_PROVENANCE,
            execution_id=f"local-{index}",
        )
        for index, value in enumerate((prompt, *WORDING_VARIANTS), start=1)
    ]
    if any(isinstance(spec, Clarification) for spec in specs):
        raise AssertionError("a required wording variant did not compile")
    spec_hashes = {spec.spec_hash for spec in specs}
    if len(spec_hashes) != 1:
        raise AssertionError("local wording variant spec_hash values differ")
    return spec_hashes.pop()


def _raw_path(output: Path, index: int) -> Path:
    return output.with_name(f"{output.stem}-run-{index}.events.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stream-url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--runs", required=True, type=int)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.runs != 3:
        raise SystemExit("--runs must be 3")

    local_spec_hash = verify_local_wording_variants(args.prompt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    event_runs = []
    for index in range(1, args.runs + 1):
        events = collect_events(args.stream_url, args.api_key, args.prompt)
        event_runs.append(events)
        _raw_path(args.output, index).write_text(
            json.dumps(events, allow_nan=False, indent=2, sort_keys=True) + "\n"
        )
    summaries = verify_runs(event_runs)
    args.output.write_text(
        json.dumps(
            {
                "status": "passed",
                "local_wording_spec_hash": local_spec_hash,
                "runs": summaries,
            },
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
