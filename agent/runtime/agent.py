"""AgentCore Runtime entrypoint: a Strands agent fronting the Chronos-2 tools.

The agent reasons with Claude Sonnet and calls the demo's 8 tools through the
AgentCore Gateway (MCP). The Gateway uses AWS_IAM auth, so MCP calls are
SigV4-signed with the Runtime's execution-role credentials.
"""
import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient
from mcp.client.streamable_http import streamablehttp_client

app = BedrockAgentCoreApp()

_HERE = os.path.dirname(__file__)
SYSTEM_PROMPT = open(os.path.join(_HERE, "system_prompt.md"), encoding="utf-8").read()
GATEWAY_URL = os.environ["GATEWAY_URL"]
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-6")


def _gateway() -> MCPClient:
    # SigV4-signed streamable-HTTP transport to the AWS_IAM gateway.
    return MCPClient(lambda: streamablehttp_client(GATEWAY_URL))


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
