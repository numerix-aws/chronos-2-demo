"""Runtime ownership of quantitative compilation and immutable manifests."""
from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
import types
import builtins
from dataclasses import replace
from pathlib import Path

import anyio
import pytest
from botocore.exceptions import ClientError

from chronos2_demo.run_spec import canonical_run_payload, compile_run_spec


RUNTIME_DIR = Path(__file__).resolve().parents[1] / "runtime"
HEADLINE_PROMPT = "Run the stage-safe headline demo."
PROVENANCE = {
    "market_snapshot_id": "market-v1",
    "market_sha256": "a" * 64,
    "covariate_snapshot_id": "covariates-v1",
    "covariate_sha256": "b" * 64,
    "chronos_endpoint": "chronos2-demo-ep",
    "chronos_model_version": "chronos-2",
    "baseline_image_digest": f"sha256:{'c' * 64}",
    "chronos_image_digest": f"sha256:{'d' * 64}",
    "agent_image_digest": f"sha256:{'e' * 64}",
    "book_version": "cross_asset_demo_v1",
    "blend_version": "importance_weight_v1",
    "pricing_version": "cross_asset_v1",
    "tool_bundle_version": "git:0123456789abcdef",
    "strands_version": "1.30.0",
}


class FakeS3:
    def __init__(self, order: list[str] | None = None) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.order = order if order is not None else []

    def put_object(self, **kwargs):
        key = (kwargs["Bucket"], kwargs["Key"])
        if key in self.objects:
            raise ClientError(
                {"Error": {"Code": "PreconditionFailed", "Message": "exists"}},
                "PutObject",
            )
        assert kwargs["IfNoneMatch"] == "*"
        assert kwargs["ContentType"] == "application/json"
        self.objects[key] = kwargs["Body"]
        self.order.append("persist")

    def get_object(self, **kwargs):
        return {"Body": io.BytesIO(self.objects[(kwargs["Bucket"], kwargs["Key"])])}


class ConflictOnceS3(FakeS3):
    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def put_object(self, **kwargs):
        self.attempts += 1
        if self.attempts == 1:
            raise ClientError(
                {
                    "Error": {
                        "Code": "ConditionalRequestConflict",
                        "Message": "concurrent write",
                    }
                },
                "PutObject",
            )
        return super().put_object(**kwargs)


class RepeatedConflictS3(FakeS3):
    def __init__(self, winner: bytes | None) -> None:
        super().__init__()
        self.winner = winner
        self.attempts = 0

    def put_object(self, **kwargs):
        self.attempts += 1
        raise ClientError(
            {
                "Error": {
                    "Code": "ConditionalRequestConflict",
                    "Message": "concurrent write",
                }
            },
            "PutObject",
        )

    def get_object(self, **kwargs):
        if self.winner is None:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "missing winner"}},
                "GetObject",
            )
        return {"Body": io.BytesIO(self.winner)}


class AccessDeniedS3(FakeS3):
    def put_object(self, **kwargs):
        raise ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "denied"}},
            "PutObject",
        )


class UnreadableWinnerS3(RepeatedConflictS3):
    def __init__(self) -> None:
        super().__init__(b"unused")

    def get_object(self, **kwargs):
        class Body:
            def read(self):
                raise OSError("winner body unreadable")

        return {"Body": Body()}


def _install_runtime_fakes(monkeypatch, order: list[str]):
    class FakeApp:
        def entrypoint(self, fn):
            return fn

        def run(self):
            return None

    class FakeAgent:
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.instances.append(self)
            order.append("model")

        async def stream_async(self, prompt):
            self.prompt = prompt
            yield {"data": "Model response"}

    class FakeBedrockModel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    fake_runtime = types.ModuleType("bedrock_agentcore.runtime")
    fake_runtime.BedrockAgentCoreApp = FakeApp
    fake_bedrock_agentcore = types.ModuleType("bedrock_agentcore")
    fake_bedrock_agentcore.runtime = fake_runtime
    fake_strands = types.ModuleType("strands")
    fake_strands.Agent = FakeAgent
    fake_models = types.ModuleType("strands.models")
    fake_models.BedrockModel = FakeBedrockModel
    fake_mcp = types.ModuleType("strands.tools.mcp")
    fake_mcp.MCPClient = object
    fake_tools = types.ModuleType("strands.tools")
    fake_tools.mcp = fake_mcp
    fake_proxy_client = types.ModuleType("mcp_proxy_for_aws.client")
    fake_proxy_client.aws_iam_streamablehttp_client = lambda **_kwargs: None
    fake_proxy = types.ModuleType("mcp_proxy_for_aws")
    fake_proxy.client = fake_proxy_client

    for name, module in {
        "bedrock_agentcore": fake_bedrock_agentcore,
        "bedrock_agentcore.runtime": fake_runtime,
        "strands": fake_strands,
        "strands.models": fake_models,
        "strands.tools": fake_tools,
        "strands.tools.mcp": fake_mcp,
        "mcp_proxy_for_aws": fake_proxy,
        "mcp_proxy_for_aws.client": fake_proxy_client,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    return FakeAgent


def _load_runtime(monkeypatch, order: list[str]):
    assert (RUNTIME_DIR / "workflow.py").exists(), "deterministic workflow is missing"
    fake_agent = _install_runtime_fakes(monkeypatch, order)
    monkeypatch.setenv("GATEWAY_URL", "https://gateway.example")
    monkeypatch.syspath_prepend(str(RUNTIME_DIR))
    sys.modules.pop("events", None)
    sys.modules.pop("workflow", None)
    real_open = builtins.open

    def runtime_open(path, *args, **kwargs):
        if Path(path) == RUNTIME_DIR / "system_prompt.md":
            path = RUNTIME_DIR.parent / "system_prompt.md"
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", runtime_open)
    spec = importlib.util.spec_from_file_location(
        "runtime_agent_task8", RUNTIME_DIR / "agent.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, fake_agent


def _set_provenance_env(monkeypatch):
    for name, env_name in {
        "market_snapshot_id": "MARKET_SNAPSHOT_ID",
        "market_sha256": "MARKET_SHA256",
        "covariate_snapshot_id": "COVARIATE_SNAPSHOT_ID",
        "covariate_sha256": "COVARIATE_SHA256",
        "chronos_endpoint": "CHRONOS2_ENDPOINT",
        "chronos_model_version": "CHRONOS_MODEL_VERSION",
        "baseline_image_digest": "BASELINE_IMAGE_DIGEST",
        "chronos_image_digest": "CHRONOS_IMAGE_DIGEST",
        "agent_image_digest": "AGENT_IMAGE_DIGEST",
        "book_version": "BOOK_VERSION",
        "blend_version": "BLEND_VERSION",
        "pricing_version": "PRICING_VERSION",
        "tool_bundle_version": "TOOL_BUNDLE_VERSION",
        "strands_version": "STRANDS_VERSION",
    }.items():
        monkeypatch.setenv(env_name, PROVENANCE[name])
    monkeypatch.setenv("DATA_BUCKET", "data-bucket")


async def _events(module, prompt: str):
    return [event async for event in module.invoke({"prompt": prompt})]


class FakeGateway:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.tools = ["lookup_use_case"]

    def __enter__(self):
        self.order.append("gateway")
        return self

    def __exit__(self, *_args):
        return None

    def list_tools_sync(self):
        return self.tools


def test_supported_run_persists_and_emits_run_spec_before_workflow_and_model(
    monkeypatch,
):
    order: list[str] = []
    module, fake_agent = _load_runtime(monkeypatch, order)
    _set_provenance_env(monkeypatch)
    s3 = FakeS3(order)
    monkeypatch.setattr(module.boto3, "client", lambda service: s3)
    monkeypatch.setattr(module, "_gateway", lambda: FakeGateway(order))
    monkeypatch.setattr(
        module,
        "compile_run_spec",
        lambda prompt, provenance: compile_run_spec(
            prompt, provenance=provenance, execution_id="run-1"
        ),
    )

    def workflow(_gateway, spec, **_kwargs):
        order.append("workflow")
        yield {"type": "tool", "name": "load_data", "status": "running"}
        return {
            "run_spec": canonical_run_payload(spec),
            "exposure": {},
            "diagnostics": {},
            "plots": {},
        }

    monkeypatch.setattr(module, "run_quantitative_workflow", workflow)

    events = anyio.run(_events, module, HEADLINE_PROMPT)

    assert events[0] == {
        "type": "run_spec",
        "execution_id": "run-1",
        "spec_hash": events[0]["spec_hash"],
        "run_spec": canonical_run_payload(
            compile_run_spec(
                HEADLINE_PROMPT,
                provenance=PROVENANCE,
                execution_id="run-1",
            )
        ),
    }
    assert order == ["persist", "gateway", "workflow", "model"]
    assert fake_agent.instances[0].kwargs["tools"] == []
    assert "deterministic quantitative workflow completed" in (
        fake_agent.instances[0].prompt.lower()
    )


def test_manifest_serialization_is_canonical_strict_and_idempotent(monkeypatch):
    order: list[str] = []
    module, _ = _load_runtime(monkeypatch, order)
    _set_provenance_env(monkeypatch)
    s3 = FakeS3()
    monkeypatch.setattr(module.boto3, "client", lambda service: s3)
    spec = compile_run_spec(
        HEADLINE_PROMPT, provenance=PROVENANCE, execution_id="run-1"
    )

    module._persist_run_spec(spec)
    module._persist_run_spec(spec)

    raw = s3.objects[("data-bucket", "runs/run-1/run_spec.json")]
    assert raw == json.dumps(
        {
            **canonical_run_payload(spec),
            "spec_hash": spec.spec_hash,
            "execution_id": spec.execution_id,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    with pytest.raises(ValueError):
        module._serialize_run_spec(replace(spec, w_stress=float("nan")))


def test_manifest_rejects_same_execution_id_with_different_canonical_bytes(monkeypatch):
    order: list[str] = []
    module, _ = _load_runtime(monkeypatch, order)
    _set_provenance_env(monkeypatch)
    s3 = FakeS3()
    monkeypatch.setattr(module.boto3, "client", lambda service: s3)
    first = compile_run_spec(
        HEADLINE_PROMPT, provenance=PROVENANCE, execution_id="run-1"
    )
    second = compile_run_spec(
        "Run the stage-safe headline demo with 600 scenarios.",
        provenance=PROVENANCE,
        execution_id="run-1",
    )

    module._persist_run_spec(first)
    with pytest.raises(RuntimeError, match="different canonical bytes"):
        module._persist_run_spec(second)


def test_manifest_retries_s3_conditional_request_conflict(monkeypatch):
    order: list[str] = []
    module, _ = _load_runtime(monkeypatch, order)
    _set_provenance_env(monkeypatch)
    s3 = ConflictOnceS3()
    monkeypatch.setattr(module.boto3, "client", lambda service: s3)
    spec = compile_run_spec(
        HEADLINE_PROMPT, provenance=PROVENANCE, execution_id="run-1"
    )

    module._persist_run_spec(spec)

    assert s3.attempts == 2
    assert ("data-bucket", "runs/run-1/run_spec.json") in s3.objects


def test_manifest_repeated_conflict_accepts_identical_winner_with_bounded_backoff(
    monkeypatch,
):
    order: list[str] = []
    module, _ = _load_runtime(monkeypatch, order)
    _set_provenance_env(monkeypatch)
    spec = compile_run_spec(
        HEADLINE_PROMPT, provenance=PROVENANCE, execution_id="run-1"
    )
    s3 = RepeatedConflictS3(module._serialize_run_spec(spec))
    sleeps = []
    monkeypatch.setattr(module.boto3, "client", lambda service: s3)
    monkeypatch.setattr(module.time, "sleep", sleeps.append)

    module._persist_run_spec(spec)

    assert s3.attempts == 3
    assert sleeps == [0.05, 0.1]


@pytest.mark.parametrize(
    "winner,error",
    [
        (b"different", "different canonical bytes"),
        (None, "winner verification failed"),
        ("unreadable", "winner verification failed"),
    ],
)
def test_manifest_repeated_conflict_rejects_invalid_winner(monkeypatch, winner, error):
    order: list[str] = []
    module, _ = _load_runtime(monkeypatch, order)
    _set_provenance_env(monkeypatch)
    s3 = (
        UnreadableWinnerS3()
        if winner == "unreadable"
        else RepeatedConflictS3(winner)
    )
    monkeypatch.setattr(module.boto3, "client", lambda service: s3)
    monkeypatch.setattr(module.time, "sleep", lambda _delay: None)
    spec = compile_run_spec(
        HEADLINE_PROMPT, provenance=PROVENANCE, execution_id="run-1"
    )

    with pytest.raises(RuntimeError, match=error):
        module._persist_run_spec(spec)

    assert s3.attempts == 3


@pytest.mark.parametrize(
    "s3_factory,error",
    [
        (lambda: AccessDeniedS3(), "run manifest persistence failed.*AccessDenied"),
        (
            lambda: RepeatedConflictS3(b"different"),
            "different canonical bytes",
        ),
        (
            lambda: RepeatedConflictS3(None),
            "winner verification failed.*NoSuchKey",
        ),
        (
            lambda: UnreadableWinnerS3(),
            "winner verification failed.*winner body unreadable",
        ),
    ],
)
def test_unrecoverable_manifest_error_is_structured_before_gateway_or_model(
    monkeypatch,
    s3_factory,
    error,
):
    order: list[str] = []
    module, fake_agent = _load_runtime(monkeypatch, order)
    _set_provenance_env(monkeypatch)
    monkeypatch.setattr(
        module,
        "compile_run_spec",
        lambda prompt, provenance: compile_run_spec(
            prompt, provenance=provenance, execution_id="run-1"
        ),
    )
    monkeypatch.setattr(module.boto3, "client", lambda service: s3_factory())
    monkeypatch.setattr(module.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(module, "_gateway", lambda: FakeGateway(order))

    events = anyio.run(_events, module, HEADLINE_PROMPT)

    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert re.search(error, events[0]["message"])
    assert order == []
    assert fake_agent.instances == []


def test_ambiguous_quantitative_prompt_never_opens_s3_gateway_or_model(monkeypatch):
    order: list[str] = []
    module, fake_agent = _load_runtime(monkeypatch, order)
    _set_provenance_env(monkeypatch)
    s3 = FakeS3(order)
    monkeypatch.setattr(module.boto3, "client", lambda service: s3)
    monkeypatch.setattr(module, "_gateway", lambda: FakeGateway(order))

    events = anyio.run(
        _events,
        module,
        "Run exposure as of 2022-09-30 with a one-year horizon.",
    )

    assert events[-1] == {"type": "done"}
    assert events[0]["type"] == "text"
    assert not s3.objects
    assert order == []
    assert fake_agent.instances == []


def test_greeting_preserves_model_selected_lookup_tools_and_streaming(monkeypatch):
    order: list[str] = []
    module, fake_agent = _load_runtime(monkeypatch, order)
    _set_provenance_env(monkeypatch)
    s3 = FakeS3(order)
    monkeypatch.setattr(module.boto3, "client", lambda service: s3)
    monkeypatch.setattr(module, "_gateway", lambda: FakeGateway(order))

    events = anyio.run(_events, module, "Hello")

    assert events == [{"type": "text", "text": "Model response"}]
    assert not s3.objects
    assert order == ["gateway", "model"]
    assert fake_agent.instances[0].kwargs["tools"] == ["lookup_use_case"]


@pytest.mark.parametrize("prompt", [
    "Run through the use cases supported by this demo",
    "Can you run through the supported use cases?",
])
def test_catalog_request_preserves_model_selected_lookup_path(monkeypatch, prompt):
    order: list[str] = []
    module, fake_agent = _load_runtime(monkeypatch, order)
    _set_provenance_env(monkeypatch)
    s3 = FakeS3(order)
    monkeypatch.setattr(module.boto3, "client", lambda service: s3)
    monkeypatch.setattr(module, "_gateway", lambda: FakeGateway(order))

    events = anyio.run(_events, module, prompt)

    assert events == [{"type": "text", "text": "Model response"}]
    assert not s3.objects
    assert order == ["gateway", "model"]
    assert fake_agent.instances[0].kwargs["tools"] == ["lookup_use_case"]


def test_failed_quantitative_workflow_never_invokes_interpretation_model(monkeypatch):
    order: list[str] = []
    module, fake_agent = _load_runtime(monkeypatch, order)
    _set_provenance_env(monkeypatch)
    s3 = FakeS3(order)
    monkeypatch.setattr(module.boto3, "client", lambda service: s3)
    monkeypatch.setattr(module, "_gateway", lambda: FakeGateway(order))
    monkeypatch.setattr(
        module,
        "compile_run_spec",
        lambda prompt, provenance: compile_run_spec(
            prompt, provenance=provenance, execution_id="run-1"
        ),
    )

    def workflow(_gateway, _spec, **_kwargs):
        order.append("workflow")
        yield {"type": "tool", "name": "load_data", "status": "failed"}
        raise RuntimeError("load_data failed: source unavailable")

    monkeypatch.setattr(module, "run_quantitative_workflow", workflow)

    events = anyio.run(_events, module, HEADLINE_PROMPT)

    assert events[-1] == {
        "type": "error",
        "message": "load_data failed: source unavailable",
    }
    assert fake_agent.instances == []
    assert order == ["persist", "gateway", "workflow"]


def test_poll_exhaustion_closes_gateway_and_skips_interpretation(monkeypatch):
    order: list[str] = []
    module, fake_agent = _load_runtime(monkeypatch, order)
    _set_provenance_env(monkeypatch)
    monkeypatch.setattr(
        module,
        "compile_run_spec",
        lambda prompt, provenance: compile_run_spec(
            prompt, provenance=provenance, execution_id="run-1"
        ),
    )
    monkeypatch.setattr(module.boto3, "client", lambda service: FakeS3(order))

    class ClosingGateway(FakeGateway):
        def __exit__(self, *_args):
            self.order.append("gateway_closed")
            return None

    monkeypatch.setattr(module, "_gateway", lambda: ClosingGateway(order))

    def workflow(_gateway, _spec, **_kwargs):
        order.append("workflow")
        yield {
            "type": "tool",
            "name": "check_baseline_mc",
            "status": "failed",
        }
        raise RuntimeError(
            "check_baseline_mc failed: polling exhausted after 3 attempts"
        )

    monkeypatch.setattr(module, "run_quantitative_workflow", workflow)

    events = anyio.run(_events, module, HEADLINE_PROMPT)

    assert events[-1]["type"] == "error"
    assert order == ["persist", "gateway", "workflow", "gateway_closed"]
    assert fake_agent.instances == []
