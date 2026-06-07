import { SecretsManagerClient, GetSecretValueCommand } from '@aws-sdk/client-secrets-manager';

type AuthEvent = {
  type: 'REQUEST';
  methodArn: string;
  headers: Record<string, string>;
};

type Policy = {
  principalId: string;
  policyDocument: {
    Version: '2012-10-17';
    Statement: Array<{ Action: string; Effect: 'Allow' | 'Deny'; Resource: string }>;
  };
};

function buildPolicy(effect: 'Allow' | 'Deny', resource: string): Policy {
  return {
    principalId: 'demo-user',
    policyDocument: {
      Version: '2012-10-17',
      Statement: [{ Action: 'execute-api:Invoke', Effect: effect, Resource: resource }],
    },
  };
}

// Resolve the expected key once per container from Secrets Manager (the ARN is
// injected as API_KEY_SECRET_ARN) and cache it across warm invocations. Tests
// inject API_KEY directly to bypass the fetch.
const sm = new SecretsManagerClient({});
let cachedKey: string | undefined;

async function expectedKey(): Promise<string | undefined> {
  if (process.env.API_KEY) return process.env.API_KEY;
  if (cachedKey) return cachedKey;
  const arn = process.env.API_KEY_SECRET_ARN;
  if (!arn) return undefined;
  const out = await sm.send(new GetSecretValueCommand({ SecretId: arn }));
  cachedKey = out.SecretString;
  return cachedKey;
}

export async function handler(event: AuthEvent): Promise<Policy> {
  const expected = await expectedKey();
  if (!expected) {
    return buildPolicy('Deny', event.methodArn);
  }
  // Case-insensitive header lookup.
  const headers = event.headers ?? {};
  const provided = Object.keys(headers).find(
    (k) => k.toLowerCase() === 'x-api-key'
  );
  if (!provided) {
    return buildPolicy('Deny', event.methodArn);
  }
  return headers[provided] === expected
    ? buildPolicy('Allow', event.methodArn)
    : buildPolicy('Deny', event.methodArn);
}
