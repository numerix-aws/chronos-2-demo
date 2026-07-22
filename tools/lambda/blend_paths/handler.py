"""Blend validated engine PathSets and write run-owned diagnostics."""
from __future__ import annotations

import io
import json
import os
import pickle

from botocore.exceptions import BotoCoreError, ClientError
import numpy as np
import pandas as pd

from chronos2_demo.augmentation import blender
from chronos2_demo.data.regimes import label_regimes, w_stress_series
from chronos2_demo.diagnostics import run_evaluation
from chronos2_demo.pricing import book as book_mod, exposure
from chronos2_demo.types import PathSet
from tools.lambda_.shared import responses, run_manifest, s3_io
from tools.lambda_.shared.bedrock import bedrock_action


CANONICAL_BOOK_ID = "cross_asset_demo_v1"


def _book(spec):
    version = spec.provenance["book_version"]
    if spec.book_id != version or version != CANONICAL_BOOK_ID:
        raise ValueError("RunSpec book identity does not authorize the canonical book")
    return book_mod.load_cross_asset_book(os.environ["BOOK_PATH"])


def _pathset(meta, spec, expected_producer: str) -> PathSet:
    if meta.producer_version != expected_producer:
        raise ValueError("PathSet producer version disagrees with RunSpec provenance")
    try:
        paths = pickle.loads(s3_io.download_bytes(meta.artifact_uri))
    except Exception as exc:
        raise ValueError(f"PathSet decode failed: {exc}") from exc
    if not isinstance(paths, PathSet) or paths.source != meta.source:
        raise ValueError("PathSet source disagrees with artifact sidecar")
    if paths.horizon != spec.horizon or paths.n_paths != spec.n_paths:
        raise ValueError("PathSet dimensions disagree with RunSpec")
    return paths


def _uniform(paths: PathSet) -> PathSet:
    return PathSet(
        paths=paths.paths,
        weights=np.full(paths.n_paths, 1.0 / paths.n_paths),
        series=list(paths.series),
        dates=paths.dates,
        source=paths.source,
    )


def _held_out(spec) -> tuple[pd.DataFrame, pd.DataFrame]:
    source_uri = f"s3://{os.environ['DATA_BUCKET']}/panel.parquet"
    raw = s3_io.download_bytes(source_uri)
    if s3_io.sha256_bytes(raw) != spec.provenance["market_sha256"]:
        raise ValueError("market snapshot content hash mismatch")
    try:
        panel = pd.read_parquet(io.BytesIO(raw))
    except Exception as exc:
        raise ValueError(f"market snapshot parquet decode failed: {exc}") from exc
    panel = panel.copy()
    panel.index = pd.DatetimeIndex(pd.to_datetime(panel.index)).normalize()
    if panel.index.has_duplicates:
        raise ValueError("market snapshot index contains duplicate dates")
    panel = panel.sort_index()
    future = panel.loc[panel.index > pd.Timestamp(spec.as_of_date)].head(spec.horizon).copy()
    regimes = pd.concat(
        [
            w_stress_series(panel),
            label_regimes(panel, threshold=spec.regime_threshold),
        ],
        axis=1,
    ).reindex(future.index)
    return future, regimes


def _put_artifact(
    raw: bytes,
    *,
    spec,
    key: str,
    content_type: str,
    artifact_kind: str,
    producer_version: str,
    source: str | None = None,
) -> tuple[str, str]:
    bucket = os.environ["DATA_BUCKET"]
    uri, digest = s3_io.upload_bytes(
        raw,
        bucket=bucket,
        key=key,
        content_type=content_type,
    )
    run_manifest.put_artifact_sidecar(
        artifact_uri=uri,
        artifact_sha256=digest,
        artifact_kind=artifact_kind,
        source=source,
        spec=spec,
        producer_version=producer_version,
    )
    return uri, digest


@bedrock_action
def handler(event: dict, _ctx) -> dict:
    try:
        spec = run_manifest.load_run_spec(event["execution_id"])
        book = _book(spec)
        parametric_meta = run_manifest.validate_artifact(
            event["parametric_uri"],
            spec=spec,
            allowed_kinds={"pathset"},
            allowed_sources={"parametric"},
        )
        chronos_meta = run_manifest.validate_artifact(
            event["chronos2_uri"],
            spec=spec,
            allowed_kinds={"pathset"},
            allowed_sources={"chronos2", "chronos2_conditional"},
        )
        parametric = _pathset(
            parametric_meta, spec, spec.provenance["baseline_image_digest"]
        )
        chronos = _pathset(
            chronos_meta, spec, spec.provenance["chronos_image_digest"]
        )
        swaps, equity_forwards, cds_protection = book
        pnl_parametric = exposure.portfolio_mtm(
            swaps,
            parametric,
            equity_forwards=equity_forwards,
            cds_protection=cds_protection,
        )[:, -1]
        pnl_chronos = exposure.portfolio_mtm(
            swaps,
            chronos,
            equity_forwards=equity_forwards,
            cds_protection=cds_protection,
        )[:, -1]
        blended = blender.blend_paths(
            parametric,
            chronos,
            pnl_parametric,
            pnl_chronos,
            w_stress=spec.w_stress,
        )
        blended_raw = pickle.dumps(blended, protocol=pickle.HIGHEST_PROTOCOL)
        prefix = f"runs/{spec.execution_id}"
        blended_uri, blended_sha256 = _put_artifact(
            blended_raw,
            spec=spec,
            key=f"{prefix}/blended.pkl",
            content_type="application/octet-stream",
            artifact_kind="pathset",
            source="blended",
            producer_version=spec.provenance["blend_version"],
        )

        future_panel, future_regimes = _held_out(spec)
        distributions = {
            "baseline": _uniform(parametric),
            "chronos_only": _uniform(chronos),
            "augmented": blended,
        }
        diagnostics = {
            "execution_id": spec.execution_id,
            "spec_hash": spec.spec_hash,
            "provenance": {"book_version": spec.provenance["book_version"]},
            "attribution": run_evaluation.compute_attribution(
                book, parametric, chronos, w_stress=spec.w_stress
            ),
            "portfolio_coverage": run_evaluation.compute_portfolio_coverage(
                book, distributions, future_panel
            ),
            "factor_coverage": run_evaluation.compute_factor_coverage(
                distributions,
                future_panel,
                future_regimes,
                regime_threshold=spec.regime_threshold,
            ),
        }
        diagnostics_raw = json.dumps(
            diagnostics,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        diagnostics_uri, diagnostics_sha256 = _put_artifact(
            diagnostics_raw,
            spec=spec,
            key=f"{prefix}/diagnostics.json",
            content_type="application/json",
            artifact_kind="diagnostics",
            producer_version=spec.provenance["blend_version"],
        )
    except (KeyError, TypeError, ValueError, BotoCoreError, ClientError) as exc:
        return responses.error(f"blend_paths validation failed: {exc}")

    return responses.ok({
        "execution_id": spec.execution_id,
        "spec_hash": spec.spec_hash,
        "blended_uri": blended_uri,
        "blended_sha256": blended_sha256,
        "diagnostics_uri": diagnostics_uri,
        "diagnostics_sha256": diagnostics_sha256,
        "diagnostics": diagnostics,
        "w_stress": spec.w_stress,
        "n_paths": int(blended.n_paths),
    })
