"""price_book tool: value the demo XCCY book on a PathSet → EE/PFE/ES.

Inputs:  {"paths_uri": str, "book_id": "demo"}
Outputs: {"ee": [..], "pfe_975": [..], "es_975": [..], "dates": ["YYYY-MM-DD", ...],
          "metrics_uri": str}

The metrics are also written to S3 as JSON so the `plot pfe_overlay` tool
(which reads baseline/augmented metrics from S3 URIs) can consume them.
"""
from __future__ import annotations
import io
import json
import os
import pickle
import uuid

import boto3

from chronos2_demo.pricing import book as book_mod, exposure
from tools.lambda_.shared import responses
from tools.lambda_.shared.bedrock import bedrock_action


def _download_pickle(uri: str):
    bucket, _, key = uri[len("s3://"):].partition("/")
    obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
    return pickle.load(io.BytesIO(obj["Body"].read()))


@bedrock_action
def handler(event: dict, _ctx) -> dict:
    book_id = event.get("book_id", "demo")
    if book_id != "demo":
        return responses.error(f"unknown book_id {book_id!r}; only 'demo' supported")
    try:
        ps = _download_pickle(event["paths_uri"])
    except KeyError:
        return responses.error("missing paths_uri")

    # The demo book ships in the Lambda layer; BOOK_PATH is set by Task 13.
    book = book_mod.load_book(os.environ["BOOK_PATH"])
    metrics = exposure.compute_metrics(book, ps)
    result = {
        "ee": [float(x) for x in metrics["ee"]],
        "pfe_975": [float(x) for x in metrics["pfe_975"]],
        "es_975": [float(x) for x in metrics["es_975"]],
        "dates": [d.strftime("%Y-%m-%d") for d in metrics["dates"]],
    }

    # Stage the metrics as JSON for the plot tool's pfe_overlay.
    bucket = os.environ["DATA_BUCKET"]
    key = f"sessions/{uuid.uuid4().hex[:12]}/metrics.json"
    boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=json.dumps(result).encode())
    result["metrics_uri"] = f"s3://{bucket}/{key}"
    return responses.ok(result)
