"""@bedrock_action is a pass-through for AgentCore Gateway: Gateway delivers
flat tool arguments and accepts the handler's JSON dict unchanged."""
from tools.lambda_.shared.bedrock import bedrock_action
from tools.lambda_.shared import responses


def test_adapter_passes_flat_event_through():
    seen = {}

    @bedrock_action
    def handler(event, _ctx):
        seen.update(event)
        return responses.ok({"echo": event["topic"]})

    out = handler({"topic": "frtb_ima_es"}, None)
    assert seen["topic"] == "frtb_ima_es"
    assert out == {"status": "ok", "result": {"echo": "frtb_ima_es"}}


def test_adapter_returns_handler_dict_unchanged():
    @bedrock_action
    def handler(event, _ctx):
        return responses.ok({"panel_uri": "s3://b/k"})

    out = handler({"as_of_date": "2022-06-30"}, None)
    assert out == {"status": "ok", "result": {"panel_uri": "s3://b/k"}}


def test_adapter_preserves_error_envelope():
    @bedrock_action
    def handler(event, _ctx):
        return responses.error("bad input")

    out = handler({}, None)
    assert out == {"status": "error", "message": "bad input"}
