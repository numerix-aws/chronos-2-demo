"""JSON response envelope for Lambda tool handlers.

Two envelope families:
  * `ok` / `error` — the tool-handler envelope (`{"status": ..., ...}`) that
    the Bedrock action-group adapter consumes.
  * `http_ok` / `http_error` — an API-Gateway proxy envelope
    (`{"statusCode": int, "body": json}`) for the REST handlers that sit
    directly behind API Gateway (sessions, invoke_agent).
"""
import json


def ok(result: dict) -> dict:
    return {"status": "ok", "result": result}


def error(message: str) -> dict:
    return {"status": "error", "message": message}


# API Gateway's defaultCorsPreflightOptions only covers OPTIONS; proxy-integration
# responses must carry the CORS header themselves or the browser blocks them.
_CORS_HEADERS = {"Access-Control-Allow-Origin": "*"}


def http_ok(body: dict, status: int = 200) -> dict:
    return {"statusCode": status, "headers": _CORS_HEADERS, "body": json.dumps(body)}


def http_error(message: str, status: int = 400) -> dict:
    return {"statusCode": status, "headers": _CORS_HEADERS, "body": json.dumps({"error": message})}
