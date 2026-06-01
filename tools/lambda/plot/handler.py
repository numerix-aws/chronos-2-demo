"""plot tool: render PFE overlay / path fan / regime ribbon → S3 PNG signed URL.

Inputs vary by spec:
  pfe_overlay:  {"spec": "pfe_overlay", "baseline_uri": str, "augmented_uri": str, "title": str}
  path_fan:     {"spec": "path_fan", "paths_uri": str, "series": str, "title": str}
  regime_ribbon:{"spec": "regime_ribbon", "regimes_uri": str, "threshold": float, "title": str}
Outputs: {"image_uri": str (presigned)}
"""
from __future__ import annotations
import io
import json
import os
import pickle
import uuid

import boto3
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from chronos2_demo.plotting import pfe_overlay, path_samples, regime_ribbon
from tools.lambda_.shared import responses, s3_io
from tools.lambda_.shared.bedrock import bedrock_action


def _download_json(uri: str) -> dict:
    bucket, _, key = uri[len("s3://"):].partition("/")
    obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
    return json.loads(obj["Body"].read())


def _download_pickle(uri: str):
    bucket, _, key = uri[len("s3://"):].partition("/")
    obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
    return pickle.load(io.BytesIO(obj["Body"].read()))


def _fig_to_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _publish(png: bytes) -> str:
    bucket = os.environ["PLOTS_BUCKET"]
    key = f"plots/{uuid.uuid4().hex[:12]}.png"
    return s3_io.upload_png_signed(png, bucket=bucket, key=key, expires_in=900)


@bedrock_action
def handler(event: dict, _ctx) -> dict:
    spec = event.get("spec")
    title = event.get("title", "")
    try:
        if spec == "pfe_overlay":
            base = _download_json(event["baseline_uri"])
            aug = _download_json(event["augmented_uri"])
            base["dates"] = pd.DatetimeIndex(base["dates"])
            aug["dates"] = pd.DatetimeIndex(aug["dates"])
            fig = pfe_overlay.plot_pfe_overlay(baseline=base, augmented=aug, title=title)
        elif spec == "path_fan":
            ps = _download_pickle(event["paths_uri"])
            fig = path_samples.plot_path_fan(
                ps, series=event["series"],
                n_path_samples=event.get("n_path_samples", 20),
                title=title,
            )
        elif spec == "regime_ribbon":
            r_df = _download_pickle(event["regimes_uri"]) if event["regimes_uri"].endswith(".pkl") \
                else s3_io.download_parquet(event["regimes_uri"])
            w = r_df["w_stress"] if hasattr(r_df, "columns") else r_df
            fig = regime_ribbon.plot_regime_ribbon(
                w, threshold=float(event.get("threshold", 0.7)), title=title
            )
        else:
            return responses.error(f"unknown spec {spec!r}")
    except KeyError as e:
        return responses.error(f"missing input: {e}")

    png = _fig_to_png(fig)
    return responses.ok({"image_uri": _publish(png), "spec": spec})
