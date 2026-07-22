"""Render validated run artifacts to deterministic, identity-bearing PNGs."""
from __future__ import annotations

import io
import os
import pickle

from botocore.exceptions import BotoCoreError, ClientError
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from chronos2_demo.execution import scenario_role
from chronos2_demo.plotting import pfe_overlay, path_samples, regime_ribbon
from chronos2_demo.types import PathSet
from tools.lambda_.shared import responses, run_manifest, s3_io
from tools.lambda_.shared.bedrock import bedrock_action


def _expected_path_producer(spec, source: str) -> str:
    if source == "parametric":
        return spec.provenance["baseline_image_digest"]
    if source in {"chronos2", "chronos2_conditional"}:
        return spec.provenance["chronos_image_digest"]
    return spec.provenance["blend_version"]


def _path_key(spec, source: str) -> str:
    filename = {
        "parametric": "baseline.pkl",
        "chronos2": "chronos2.pkl",
        "chronos2_conditional": "chronos2.pkl",
        "blended": "blended.pkl",
    }[source]
    return f"runs/{spec.execution_id}/{filename}"


def _validated_path_meta(uri: str, spec, source: str):
    expected_key = _path_key(spec, source)
    meta = run_manifest.validate_artifact(
        uri,
        spec=spec,
        allowed_kinds={"pathset"},
        allowed_sources={source},
        expected_key=expected_key,
        expected_uri=f"s3://{os.environ['DATA_BUCKET']}/{expected_key}",
    )
    if meta.producer_version != _expected_path_producer(spec, source):
        raise ValueError("PathSet producer version disagrees with RunSpec provenance")
    return meta


def _metrics(uri: str, spec) -> dict:
    _, key = s3_io.split_s3_uri(uri)
    canonical_keys = {
        f"runs/{spec.execution_id}/metrics/{role}.json"
        for role in ("baseline", "chronos_only", "augmented")
    }
    if key not in canonical_keys:
        raise ValueError("metrics key does not match an exact scenario-role key")
    meta = run_manifest.validate_artifact(
        uri,
        spec=spec,
        allowed_kinds={"metrics"},
        allowed_sources={"parametric", "chronos2", "chronos2_conditional", "blended"},
        expected_key=key,
    )
    if meta.producer_version != spec.provenance["pricing_version"]:
        raise ValueError("metrics producer version disagrees with RunSpec provenance")
    payload = s3_io.download_json(meta.artifact_uri)
    role = scenario_role(meta.source)
    expected_key = f"runs/{spec.execution_id}/metrics/{role}.json"
    if key != expected_key:
        raise ValueError("metrics source does not match its exact scenario-role key")
    if (
        payload["execution_id"] != spec.execution_id
        or payload["spec_hash"] != spec.spec_hash
        or payload["source"] != meta.source
        or payload["scenario_role"] != role
    ):
        raise ValueError("metrics content identity disagrees with artifact sidecar")
    path_meta = _validated_path_meta(payload["paths_uri"], spec, meta.source)
    if payload["paths_sha256"] != path_meta.artifact_sha256:
        raise ValueError("metrics paths hash disagrees with PathSet artifact")
    lengths = {
        len(payload[name]) for name in ("ee", "pfe_975", "es_975", "dates")
    }
    if lengths != {spec.horizon}:
        raise ValueError("metrics profile lengths disagree with RunSpec horizon")
    payload["dates"] = pd.DatetimeIndex(payload["dates"])
    return payload


def _fig_to_png(fig) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=120, bbox_inches="tight")
    return buffer.getvalue()


def _publish(png: bytes, *, spec, plot_role: str) -> dict:
    bucket = os.environ["PLOTS_BUCKET"]
    key = f"runs/{spec.execution_id}/plots/{plot_role}.png"
    image_s3_uri = f"s3://{bucket}/{key}"
    image_sha256 = s3_io.sha256_bytes(png)
    image_uri = s3_io.upload_png_signed(
        png,
        bucket=bucket,
        key=key,
        expires_in=3600,
    )
    run_manifest.put_artifact_sidecar(
        artifact_uri=image_s3_uri,
        artifact_sha256=image_sha256,
        artifact_kind="plot",
        spec=spec,
        producer_version=spec.provenance["tool_bundle_version"],
    )
    meta = run_manifest.validate_artifact(
        image_s3_uri,
        spec=spec,
        allowed_kinds={"plot"},
        expected_bucket=bucket,
        expected_key=key,
        expected_uri=image_s3_uri,
    )
    if meta.producer_version != spec.provenance["tool_bundle_version"]:
        raise ValueError("plot producer version disagrees with RunSpec provenance")
    return {
        "image_s3_uri": image_s3_uri,
        "image_uri": image_uri,
        "image_sha256": image_sha256,
    }


@bedrock_action
def handler(event: dict, _ctx) -> dict:
    fig = None
    try:
        spec = run_manifest.load_run_spec(event["execution_id"])
        plot_role = event["spec"]
        if plot_role == "pfe_overlay":
            payloads = [
                _metrics(event["baseline_uri"], spec),
                _metrics(event["augmented_uri"], spec),
            ]
            by_role = {payload["scenario_role"]: payload for payload in payloads}
            if len(by_role) != 2 or set(by_role) != {"baseline", "augmented"}:
                raise ValueError("pfe_overlay requires exactly baseline and augmented metrics")
            fig = pfe_overlay.plot_pfe_overlay(
                baseline=by_role["baseline"],
                augmented=by_role["augmented"],
                title="PFE overlay",
            )
        elif plot_role == "regime_ribbon":
            meta = run_manifest.validate_artifact(
                event["regimes_uri"],
                spec=spec,
                allowed_kinds={"regimes"},
                expected_key=f"runs/{spec.execution_id}/regimes.parquet",
            )
            if meta.source is not None or (
                meta.producer_version != spec.provenance["tool_bundle_version"]
            ):
                raise ValueError("regime artifact provenance disagrees with RunSpec")
            regimes = s3_io.download_parquet(meta.artifact_uri)
            fig = regime_ribbon.plot_regime_ribbon(
                regimes["w_stress"],
                threshold=spec.regime_threshold,
                title="Regime ribbon",
            )
        elif plot_role == "path_fan":
            _, supplied_key = s3_io.split_s3_uri(event["paths_uri"])
            canonical_keys = {
                f"runs/{spec.execution_id}/baseline.pkl",
                f"runs/{spec.execution_id}/chronos2.pkl",
                f"runs/{spec.execution_id}/blended.pkl",
            }
            if supplied_key not in canonical_keys:
                raise ValueError("PathSet key does not match an exact producer-owned key")
            meta = run_manifest.validate_artifact(
                event["paths_uri"],
                spec=spec,
                allowed_kinds={"pathset"},
                allowed_sources={
                    "parametric", "chronos2", "chronos2_conditional", "blended"
                },
                expected_key=supplied_key,
            )
            if supplied_key != _path_key(spec, meta.source):
                raise ValueError("PathSet source does not match its exact producer-owned key")
            if meta.producer_version != _expected_path_producer(spec, meta.source):
                raise ValueError("PathSet producer version disagrees with RunSpec provenance")
            try:
                paths = pickle.loads(s3_io.download_bytes(meta.artifact_uri))
            except Exception as exc:
                raise ValueError(f"PathSet pickle decode failed: {exc}") from exc
            if not isinstance(paths, PathSet) or paths.source != meta.source:
                raise ValueError("PathSet source disagrees with artifact sidecar")
            fig = path_samples.plot_path_fan(
                paths,
                series=event["series"],
                n_path_samples=event.get("n_path_samples", 20),
                title="Path fan",
            )
        else:
            return responses.error(f"unknown spec {plot_role!r}")
        png = _fig_to_png(fig)
        published = _publish(png, spec=spec, plot_role=plot_role)
    except (KeyError, TypeError, ValueError, BotoCoreError, ClientError) as exc:
        return responses.error(f"plot validation failed: {exc}")
    finally:
        if fig is not None:
            plt.close(fig)

    return responses.ok({
        "execution_id": spec.execution_id,
        "spec_hash": spec.spec_hash,
        "plot_role": plot_role,
        "spec": plot_role,
        **published,
    })
