"""AgentCore Runtime entrypoint: a Strands agent fronting the Chronos-2 tools.

The agent reasons with Claude Sonnet and calls the demo's 9 tools through the
AgentCore Gateway (MCP). The Gateway uses AWS_IAM auth, so MCP calls are
SigV4-signed with the Runtime's execution-role credentials.
"""
import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient
from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client

app = BedrockAgentCoreApp()

_HERE = os.path.dirname(__file__)
SYSTEM_PROMPT = open(os.path.join(_HERE, "system_prompt.md"), encoding="utf-8").read()
GATEWAY_URL = os.environ["GATEWAY_URL"]
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-6")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


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


@app.entrypoint
def invoke(payload: dict) -> str:
    prompt = payload.get("prompt", "")
    with _gateway() as gateway:
        tools = gateway.list_tools_sync()
        agent = Agent(
            model=BedrockModel(model_id=MODEL_ID),
            system_prompt=SYSTEM_PROMPT,
            tools=tools,
        )
        return str(agent(prompt))


if __name__ == "__main__":
    app.run()
