// Node 20 streaming entrypoint for the SSE relay.
// Wraps AgentCore Runtime's streaming response into Server-Sent Events.
import {
  BedrockAgentCoreClient,
  InvokeAgentRuntimeCommand,
} from '@aws-sdk/client-bedrock-agentcore';
import { SecretsManagerClient, GetSecretValueCommand } from '@aws-sdk/client-secrets-manager';
import { handleRelayRequest } from './protocol.mjs';

const agentClient = new BedrockAgentCoreClient({});
const secretsClient = new SecretsManagerClient({});

export function createGetApiKey(client = secretsClient) {
  return async function getApiKey() {
    const out = await client.send(
      new GetSecretValueCommand({ SecretId: process.env.API_KEY_SECRET_ARN })
    );
    return out.SecretString;
  };
}

export const getApiKey = createGetApiKey();

export const handler = awslambda.streamifyResponse(async (event, responseStream) => {
  await handleRelayRequest(event, responseStream, {
    getApiKey,
    createResponseStream(stream, metadata) {
      return awslambda.HttpResponseStream.from(stream, metadata);
    },
    async invokeAgent({ sessionId, prompt }) {
      const command = new InvokeAgentRuntimeCommand({
        agentRuntimeArn: process.env.AGENT_RUNTIME_ARN,
        runtimeSessionId: sessionId,
        qualifier: process.env.AGENT_QUALIFIER,
        payload: new TextEncoder().encode(JSON.stringify({ prompt })),
      });
      return agentClient.send(command);
    },
    setIntervalFn: setInterval,
    clearIntervalFn: clearInterval,
  });
});
