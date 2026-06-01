from unittest.mock import patch

from tools.lambda_.check_baseline_mc import handler


def _describe(last_status, exit_code=0):
    container = {"name": "App", "lastStatus": last_status}
    if exit_code is not None:
        container["exitCode"] = exit_code
    return {"tasks": [{"lastStatus": last_status, "containers": [container]}], "failures": []}


def test_check_reports_running(monkeypatch):
    monkeypatch.setenv("CLUSTER_ARN", "baseline-mc")
    with patch.object(handler, "_describe_task", return_value=_describe("RUNNING", exit_code=None)):
        out = handler.handler({"task_arn": "arn:task/abc", "paths_uri": "s3://b/k.pkl"}, None)
    assert out["status"] == "ok"
    assert out["result"]["task_status"] == "RUNNING"
    assert out["result"]["ready"] is False


def test_check_reports_ready_when_stopped_ok(monkeypatch):
    monkeypatch.setenv("CLUSTER_ARN", "baseline-mc")
    with patch.object(handler, "_describe_task", return_value=_describe("STOPPED", exit_code=0)):
        out = handler.handler({"task_arn": "arn:task/abc", "paths_uri": "s3://b/k.pkl"}, None)
    assert out["result"]["ready"] is True
    assert out["result"]["paths_uri"] == "s3://b/k.pkl"


def test_check_reports_failure_when_stopped_nonzero(monkeypatch):
    monkeypatch.setenv("CLUSTER_ARN", "baseline-mc")
    with patch.object(handler, "_describe_task", return_value=_describe("STOPPED", exit_code=1)):
        out = handler.handler({"task_arn": "arn:task/abc", "paths_uri": "s3://b/k.pkl"}, None)
    assert out["status"] == "error"


def test_check_rejects_missing_task_arn(monkeypatch):
    monkeypatch.setenv("CLUSTER_ARN", "baseline-mc")
    out = handler.handler({"paths_uri": "s3://b/k.pkl"}, None)
    assert out["status"] == "error"
    assert "task_arn" in out["message"]
