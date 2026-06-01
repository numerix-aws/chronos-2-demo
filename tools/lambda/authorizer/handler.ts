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

export async function handler(event: AuthEvent): Promise<Policy> {
  const expected = process.env.API_KEY;
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
