// Node 20 streaming entrypoint for the SSE relay.
// Wraps AgentCore Runtime's streaming response into Server-Sent Events.
import {
  BedrockAgentCoreClient,
  InvokeAgentRuntimeCommand,
} from '@aws-sdk/client-bedrock-agentcore';
import { SecretsManagerClient, GetSecretValueCommand } from '@aws-sdk/client-secrets-manager';

const agentClient = new BedrockAgentCoreClient({});
const secretsClient = new SecretsManagerClient({});

let cachedKey = null;
async function getApiKey() {
  if (cachedKey) return cachedKey;
  const out = await secretsClient.send(
    new GetSecretValueCommand({ SecretId: process.env.API_KEY_SECRET_ARN })
  );
  cachedKey = out.SecretString;
  return cachedKey;
}

function isAuthorized(headers, key) {
  for (const [name, value] of Object.entries(headers || {})) {
    if (name.toLowerCase() === 'x-api-key' && value === key) return true;
  }
  return false;
}

function sseFrame(text) {
  return text.split('\n').map((l) => `data: ${l}\n`).join('') + '\n';
}

export const handler = awslambda.streamifyResponse(async (event, responseStream) => {
  const headers = event.headers || {};
  const key = await getApiKey();
  if (!isAuthorized(headers, key)) {
    responseStream.setContentType('text/plain');
    responseStream.write('unauthorized');
    responseStream.end();
    return;
  }

  const qs = event.queryStringParameters || {};
  const sessionId = qs.session_id;
  const prompt = qs.prompt;
  if (!sessionId || !prompt) {
    responseStream.setContentType('text/plain');
    responseStream.write('session_id and prompt required');
    responseStream.end();
    return;
  }

  responseStream.setContentType('text/event-stream');
  // Flush a comment frame immediately and heartbeat while the agent is in
  // long tool calls: CloudFront's origin read timeout (30s) aborts the stream
  // if no bytes arrive, and the agent can go minutes before its first token.
  responseStream.write(': connected\n\n');
  const heartbeat = setInterval(() => responseStream.write(': keepalive\n\n'), 15000);

  try {
    const cmd = new InvokeAgentRuntimeCommand({
      agentRuntimeArn: process.env.AGENT_RUNTIME_ARN,
      runtimeSessionId: sessionId,
      payload: new TextEncoder().encode(JSON.stringify({ prompt })),
    });
    const response = await agentClient.send(cmd);
    for await (const chunk of response.response) {
      const text = Buffer.from(chunk).toString('utf-8');
      responseStream.write(sseFrame(text));
    }
    responseStream.write(sseFrame('[DONE]'));
  } catch (err) {
    responseStream.write(sseFrame(`[ERROR] ${err.message}`));
  } finally {
    clearInterval(heartbeat);
    responseStream.end();
  }
});
