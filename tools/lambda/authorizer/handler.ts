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

const sm = new SecretsManagerClient({});

type GetSecret = () => Promise<string | undefined>;

async function fetchSecret(): Promise<string | undefined> {
  const arn = process.env.API_KEY_SECRET_ARN;
  if (!arn) return undefined;
  const out = await sm.send(new GetSecretValueCommand({ SecretId: arn }));
  return out.SecretString;
}

async function expectedKey(getSecret: GetSecret): Promise<string | undefined> {
  if (process.env.API_KEY) return process.env.API_KEY;
  return getSecret();
}

export function createHandler({ getSecret = fetchSecret }: { getSecret?: GetSecret } = {}) {
  return async function handler(event: AuthEvent): Promise<Policy> {
    const expected = await expectedKey(getSecret);
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
    // Keep Allow scoped to the whole API stage rather than a single method ARN.
    return headers[provided] === expected
      ? buildPolicy('Allow', apiWildcard(event.methodArn))
      : buildPolicy('Deny', event.methodArn);
  };
}

export const handler = createHandler();

// arn:aws:execute-api:region:acct:apiId/stage/METHOD/path -> .../apiId/*
function apiWildcard(methodArn: string): string {
  const parts = methodArn.split(':');
  const apiId = (parts[5] ?? '').split('/')[0];
  return `${parts.slice(0, 5).join(':')}:${apiId}/*`;
}
