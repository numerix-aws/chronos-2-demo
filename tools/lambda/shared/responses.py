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


def http_ok(body: dict, status: int = 200) -> dict:
    return {"statusCode": status, "body": json.dumps(body)}


def http_error(message: str, status: int = 400) -> dict:
    return {"statusCode": status, "body": json.dumps({"error": message})}
