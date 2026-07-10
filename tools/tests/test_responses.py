from tools.lambda_.shared import responses


def test_ok_envelope_shape():
    out = responses.ok({"x": 1})
    assert out["status"] == "ok"
    assert out["result"] == {"x": 1}


def test_error_envelope_shape():
    out = responses.error("bad input")
    assert out["status"] == "error"
    assert out["message"] == "bad input"


def test_ok_round_trips_through_json():
    import json
    out = responses.ok({"arr": [1, 2, 3]})
    assert json.loads(json.dumps(out)) == out


def test_http_ok_wraps_body_with_status_code():
    import json
    out = responses.http_ok({"session_id": "s1"})
    assert out["statusCode"] == 200
    assert json.loads(out["body"]) == {"session_id": "s1"}


def test_http_error_defaults_to_400_with_error_key():
    import json
    out = responses.http_error("bad role")
    assert out["statusCode"] == 400
    assert json.loads(out["body"]) == {"error": "bad role"}


def test_http_error_custom_status():
    out = responses.http_error("nope", status=404)
    assert out["statusCode"] == 404


def test_http_ok_includes_cors_headers():
    out = responses.http_ok({"session_id": "s1"})
    assert out["headers"]["Access-Control-Allow-Origin"] == "*"


def test_http_error_includes_cors_headers():
    out = responses.http_error("bad role")
    assert out["headers"]["Access-Control-Allow-Origin"] == "*"
