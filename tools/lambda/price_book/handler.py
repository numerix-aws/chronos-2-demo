"""Price a validated PathSet with the canonical cross-asset book."""
from __future__ import annotations

import json
import os
import pickle

from botocore.exceptions import BotoCoreError, ClientError

from chronos2_demo.execution import scenario_role
from chronos2_demo.pricing import book as book_mod, exposure
from chronos2_demo.types import PathSet
from tools.lambda_.shared import responses, run_manifest, s3_io
from tools.lambda_.shared.bedrock import bedrock_action


CANONICAL_BOOK_ID = "cross_asset_demo_v1"


def _expected_producer(spec, source: str) -> str:
    if source == "parametric":
        return spec.provenance["baseline_image_digest"]
    if source in {"chronos2", "chronos2_conditional"}:
        return spec.provenance["chronos_image_digest"]
    return spec.provenance["blend_version"]


def _book(spec):
    version = spec.provenance["book_version"]
    if spec.book_id != version or version != CANONICAL_BOOK_ID:
        raise ValueError("RunSpec book identity does not authorize the canonical book")
    return book_mod.load_cross_asset_book(os.environ["BOOK_PATH"])


def _json_bytes(payload: dict) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _put_metrics(payload: dict, *, spec, source: str, role: str) -> tuple[str, str]:
    bucket = os.environ["DATA_BUCKET"]
    key = f"runs/{spec.execution_id}/metrics/{role}.json"
    uri = f"s3://{bucket}/{key}"
    raw = _json_bytes(payload)
    digest = s3_io.sha256_bytes(raw)
    try:
        existing = s3_io.download_bytes(uri)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey"}:
            raise
    else:
        if existing != raw:
            raise ValueError(f"refusing to overwrite existing metrics role {role!r}")
        meta = run_manifest.validate_artifact(
            uri,
            spec=spec,
            allowed_kinds={"metrics"},
            allowed_sources={source},
        )
        if meta.producer_version != spec.provenance["pricing_version"]:
            raise ValueError("metrics producer version disagrees with RunSpec provenance")
        return uri, digest

    uri, digest = s3_io.upload_bytes(
        raw,
        bucket=bucket,
        key=key,
        content_type="application/json",
    )
    run_manifest.put_artifact_sidecar(
        artifact_uri=uri,
        artifact_sha256=digest,
        artifact_kind="metrics",
        source=source,
        spec=spec,
        producer_version=spec.provenance["pricing_version"],
    )
    return uri, digest


@bedrock_action
def handler(event: dict, _ctx) -> dict:
    try:
        spec = run_manifest.load_run_spec(event["execution_id"])
        meta = run_manifest.validate_artifact(
            event["paths_uri"],
            spec=spec,
            allowed_kinds={"pathset"},
            allowed_sources={
                "parametric", "chronos2", "chronos2_conditional", "blended"
            },
        )
        expected_producer = _expected_producer(spec, meta.source)
        if meta.producer_version != expected_producer:
            raise ValueError("PathSet producer version disagrees with RunSpec provenance")
        try:
            paths = pickle.loads(s3_io.download_bytes(meta.artifact_uri))
        except Exception as exc:
            raise ValueError(f"PathSet decode failed: {exc}") from exc
        if not isinstance(paths, PathSet) or paths.source != meta.source:
            raise ValueError("PathSet source disagrees with artifact sidecar")
        if paths.horizon != spec.horizon:
            raise ValueError("PathSet horizon disagrees with RunSpec")
        role = scenario_role(paths.source)
        if role != meta.scenario_role:
            raise ValueError("PathSet source disagrees with artifact sidecar role")

        swaps, equity_forwards, cds_protection = _book(spec)
        metrics = exposure.compute_metrics(
            swaps,
            paths,
            q=0.975,
            equity_forwards=equity_forwards,
            cds_protection=cds_protection,
        )
        dates = [value.strftime("%Y-%m-%d") for value in metrics["dates"]]
        payload = {
            "execution_id": spec.execution_id,
            "spec_hash": spec.spec_hash,
            "scenario_role": role,
            "source": paths.source,
            "paths_uri": meta.artifact_uri,
            "paths_sha256": meta.artifact_sha256,
            "ee": [float(value) for value in metrics["ee"]],
            "pfe_975": [float(value) for value in metrics["pfe_975"]],
            "es_975": [float(value) for value in metrics["es_975"]],
            "dates": dates,
            "terminal": {
                "date": dates[-1],
                "ee": float(metrics["ee"][-1]),
                "pfe_975": float(metrics["pfe_975"][-1]),
                "es_975": float(metrics["es_975"][-1]),
            },
        }
        metrics_uri, metrics_sha256 = _put_metrics(
            payload,
            spec=spec,
            source=paths.source,
            role=role,
        )
    except (KeyError, TypeError, ValueError, BotoCoreError, ClientError) as exc:
        return responses.error(f"price_book validation failed: {exc}")

    payload.update({
        "metrics_uri": metrics_uri,
        "metrics_sha256": metrics_sha256,
    })
    return responses.ok(payload)
