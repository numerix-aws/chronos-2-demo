"""load_data tool: slice a lookback window from the curated panel.

Inputs:  {"as_of_date": "YYYY-MM-DD", "lookback_days": int}
Outputs: {"panel_uri": str, "regimes_uri": str, "n_rows": int}
"""
from __future__ import annotations
import os
import uuid
from datetime import datetime

import pandas as pd

from tools.lambda_.shared import responses, s3_io
from tools.lambda_.shared.bedrock import bedrock_action


@bedrock_action
def handler(event: dict, _ctx) -> dict:
    try:
        as_of = datetime.fromisoformat(event["as_of_date"])
    except (KeyError, ValueError) as e:
        return responses.error(f"as_of_date invalid: {e}")
    lookback = int(event.get("lookback_days", 60))
    if lookback <= 0 or lookback > 5000:
        return responses.error("lookback_days must be in (0, 5000]")

    bucket = os.environ["DATA_BUCKET"]
    panel = s3_io.download_parquet(f"s3://{bucket}/panel.parquet")
    regimes = s3_io.download_parquet(f"s3://{bucket}/regimes.parquet")

    panel.index = pd.DatetimeIndex(panel.index)
    regimes.index = pd.DatetimeIndex(regimes.index)
    end = pd.Timestamp(as_of)
    if end < panel.index.min() or end > panel.index.max():
        return responses.error(
            f"as_of_date {as_of.date()} outside panel range "
            f"[{panel.index.min().date()}, {panel.index.max().date()}]"
        )

    sliced = panel.loc[:end].tail(lookback)
    sliced_r = regimes.loc[sliced.index]
    if len(sliced) < lookback:
        return responses.error(
            f"only {len(sliced)} rows available before {as_of.date()}, "
            f"need {lookback}"
        )

    sid = uuid.uuid4().hex[:12]
    panel_key = f"sessions/{sid}/panel.parquet"
    regimes_key = f"sessions/{sid}/regimes.parquet"
    panel_uri = s3_io.upload_parquet(sliced, bucket=bucket, key=panel_key)
    regimes_uri = s3_io.upload_parquet(sliced_r, bucket=bucket, key=regimes_key)
    return responses.ok({
        "panel_uri": panel_uri,
        "regimes_uri": regimes_uri,
        "n_rows": int(len(sliced)),
    })
