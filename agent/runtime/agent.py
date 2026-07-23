"""AgentCore Runtime entrypoint: a Strands agent fronting the Chronos-2 tools.

The agent reasons with Claude Sonnet and calls the demo's 9 tools through the
AgentCore Gateway (MCP). The Gateway uses AWS_IAM auth, so MCP calls are
SigV4-signed with the Runtime's execution-role credentials.
"""
import json
import os

import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from botocore.exceptions import ClientError
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient
from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
from chronos2_demo.run_spec import (
    Clarification,
    canonical_run_payload,
    compile_run_spec,
)
from events import StrandsEventTranslator
from workflow import run_quantitative_workflow

app = BedrockAgentCoreApp()

_HERE = os.path.dirname(__file__)
SYSTEM_PROMPT = open(os.path.join(_HERE, "system_prompt.md"), encoding="utf-8").read()
GATEWAY_URL = os.environ["GATEWAY_URL"]
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-6")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

PROVENANCE_ENV = {
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
}


def _gateway() -> MCPClient:
    # SigV4-signed streamable-HTTP transport to the AWS_IAM Gateway, using the
    # Runtime execution-role credentials (mcp-proxy-for-aws handles signing). A
    # plain streamablehttp_client would be unsigned and the Gateway returns 403.
    # timeout must exceed the slowest Gateway tool call (blend/price run >30s
    # on the headline load); the default 30s ReadTimeout kills the MCP session
    # mid-conversation and the invocation 500s.
    return MCPClient(lambda: aws_iam_streamablehttp_client(
        endpoint=GATEWAY_URL,
        aws_region=AWS_REGION,
        aws_service="bedrock-agentcore",
        timeout=180,
    ))


def _provenance() -> dict[str, str]:
    missing = [
        env_name for env_name in PROVENANCE_ENV.values()
        if not os.environ.get(env_name)
    ]
    if missing:
        raise RuntimeError(f"missing deployment provenance: {missing}")
    return {
        name: os.environ[env_name]
        for name, env_name in PROVENANCE_ENV.items()
    }


def _run_spec_document(spec) -> dict:
    return {
        **canonical_run_payload(spec),
        "spec_hash": spec.spec_hash,
        "execution_id": spec.execution_id,
    }


def _serialize_run_spec(spec) -> bytes:
    return json.dumps(
        _run_spec_document(spec),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _persist_run_spec(spec) -> None:
    raw = _serialize_run_spec(spec)
    client = boto3.client("s3")
    bucket = os.environ["DATA_BUCKET"]
    key = f"runs/{spec.execution_id}/run_spec.json"
    for attempt in range(3):
        try:
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=raw,
                ContentType="application/json",
                IfNoneMatch="*",
            )
            return
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"ConditionalRequestConflict", "409"} and attempt < 2:
                continue
            if code not in {"PreconditionFailed", "412"}:
                raise
            break
    existing = client.get_object(Bucket=bucket, Key=key)["Body"].read()
    if existing != raw:
        raise RuntimeError(
            f"run manifest {key} already exists with different canonical bytes"
        )


@app.entrypoint
async def invoke(payload: dict):
    prompt = str(payload.get("prompt", ""))
    compiled = compile_run_spec(prompt, provenance=_provenance())
    if isinstance(compiled, Clarification) and compiled.is_quantitative:
        yield {"type": "text", "text": compiled.message}
        yield {"type": "done"}
        return
    if not isinstance(compiled, Clarification):
        try:
            _persist_run_spec(compiled)
        except RuntimeError as exc:
            yield {"type": "error", "message": str(exc)}
            return
        yield {
            "type": "run_spec",
            "execution_id": compiled.execution_id,
            "spec_hash": compiled.spec_hash,
            "run_spec": canonical_run_payload(compiled),
        }
        with _gateway() as gateway:
            try:
                workflow_events = run_quantitative_workflow(gateway, compiled)
                while True:
                    try:
                        outgoing = next(workflow_events)
                    except StopIteration as completed:
                        workflow = completed.value
                        break
                    yield outgoing
            except RuntimeError as exc:
                yield {"type": "error", "message": str(exc)}
                return
        model_prompt = (
            f"{prompt}\n\nThe deterministic quantitative workflow completed. "
            "Interpret these structured results without changing any value: "
            f"{json.dumps(workflow, sort_keys=True, allow_nan=False)}"
        )
        agent = Agent(
            model=BedrockModel(model_id=MODEL_ID),
            system_prompt=SYSTEM_PROMPT,
            tools=[],
            callback_handler=None,
        )
        translator = StrandsEventTranslator()
        async for event in agent.stream_async(model_prompt):
            for outgoing in translator.translate(event):
                yield outgoing
        return
    with _gateway() as gateway:
        tools = gateway.list_tools_sync()
        agent = Agent(
            model=BedrockModel(model_id=MODEL_ID),
            system_prompt=SYSTEM_PROMPT,
            tools=tools,
            callback_handler=None,
        )
        translator = StrandsEventTranslator()
        async for event in agent.stream_async(prompt):
            for outgoing in translator.translate(event):
                yield outgoing


if __name__ == "__main__":
    app.run()
