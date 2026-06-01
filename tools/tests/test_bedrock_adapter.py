"""The @bedrock_action adapter bridges Bedrock's nested action-group event
shape to the flat-dict handlers and re-wraps the {status,result} envelope
into Bedrock's {response} shape."""
import json

from tools.lambda_.shared.bedrock import bedrock_action
from tools.lambda_.shared import responses


def _bedrock_event(action_group: str, api_path: str, props: dict) -> dict:
    """Minimal Bedrock action-group invocation event."""
    return {
        "messageVersion": "1.0",
        "actionGroup": action_group,
        "apiPath": api_path,
        "httpMethod": "POST",
        "requestBody": {
            "content": {
                "application/json": {
                    "properties": [
                        {"name": k, "type": "string", "value": v}
                        for k, v in props.items()
                    ]
                }
            }
        },
    }


def test_adapter_unpacks_properties_into_flat_event():
    seen = {}

    @bedrock_action
    def handler(event, _ctx):
        seen.update(event)
        return responses.ok({"echo": event["topic"]})

    handler(_bedrock_event("ag", "/lookup_use_case", {"topic": "frtb_ima_es"}), None)
    assert seen["topic"] == "frtb_ima_es"


def test_adapter_wraps_ok_envelope_into_bedrock_response():
    @bedrock_action
    def handler(event, _ctx):
        return responses.ok({"panel_uri": "s3://b/k"})

    out = handler(_bedrock_event("ag", "/load_data", {"as_of_date": "2022-06-30"}), None)
    body = out["response"]["responseBody"]["application/json"]["body"]
    assert out["response"]["apiPath"] == "/load_data"
    assert json.loads(body) == {"status": "ok", "result": {"panel_uri": "s3://b/k"}}
    assert out["response"]["httpStatusCode"] == 200


def test_adapter_maps_error_envelope_to_400():
    @bedrock_action
    def handler(event, _ctx):
        return responses.error("bad input")

    out = handler(_bedrock_event("ag", "/load_data", {}), None)
    assert out["response"]["httpStatusCode"] == 400
