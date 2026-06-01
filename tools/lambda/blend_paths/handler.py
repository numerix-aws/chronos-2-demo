"""blend_paths tool: importance-blend parametric + Chronos-2 path sets.

Inputs:  {"parametric_uri": str, "chronos2_uri": str, "w_stress": float}
Outputs: {"blended_uri": str, "w_stress": float, "n_paths": int}
"""
from __future__ import annotations
import io
import os
import pickle
import uuid

import boto3

from chronos2_demo.augmentation import blender
from chronos2_demo.pricing import book as book_mod, exposure
from tools.lambda_.shared import responses
from tools.lambda_.shared.bedrock import bedrock_action


def _download_pickle(uri: str):
    bucket, _, key = uri[len("s3://"):].partition("/")
    obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
    return pickle.load(io.BytesIO(obj["Body"].read()))


def _upload_pickle(obj, bucket: str, key: str) -> str:
    buf = io.BytesIO()
    pickle.dump(obj, buf)
    boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    return f"s3://{bucket}/{key}"


@bedrock_action
def handler(event: dict, _ctx) -> dict:
    try:
        w_stress = float(event["w_stress"])
    except (KeyError, ValueError, TypeError) as e:
        return responses.error(f"w_stress invalid: {e}")
    if not 0.0 <= w_stress <= 1.0:
        return responses.error("w_stress must be in [0, 1]")

    try:
        para = _download_pickle(event["parametric_uri"])
        chr2 = _download_pickle(event["chronos2_uri"])
    except KeyError as e:
        return responses.error(f"missing input uri: {e}")

    # Plan A's blender importance-weights each engine by its terminal-MtM P&L,
    # so price the demo book on both PathSets first. The book ships in the layer.
    swaps = book_mod.load_book(os.environ["BOOK_PATH"])
    pnl_parametric = exposure.portfolio_mtm(swaps, para)[:, -1]
    pnl_chronos2 = exposure.portfolio_mtm(swaps, chr2)[:, -1]

    blended = blender.blend_paths(
        para, chr2, pnl_parametric, pnl_chronos2, w_stress=w_stress
    )

    bucket = os.environ["DATA_BUCKET"]
    sid = uuid.uuid4().hex[:12]
    uri = _upload_pickle(blended, bucket=bucket, key=f"sessions/{sid}/blended.pkl")
    return responses.ok({
        "blended_uri": uri,
        "w_stress": w_stress,
        "n_paths": int(blended.paths.shape[0]),
    })
