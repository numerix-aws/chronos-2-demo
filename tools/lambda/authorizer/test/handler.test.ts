import { handler } from '../handler';

const baseEvent = {
  type: 'REQUEST',
  methodArn: 'arn:aws:execute-api:us-east-1:123:api/prod/POST/agent',
  headers: {} as Record<string, string>,
};

describe('authorizer', () => {
  beforeEach(() => {
    process.env.API_KEY = 'expected-key';
  });

  test('Allow when header matches', async () => {
    const ev = { ...baseEvent, headers: { 'x-api-key': 'expected-key' } };
    const out = await handler(ev as any);
    expect(out.policyDocument.Statement[0].Effect).toBe('Allow');
  });

  test('Deny when header missing', async () => {
    const out = await handler(baseEvent as any);
    expect(out.policyDocument.Statement[0].Effect).toBe('Deny');
  });

  test('Deny when header wrong', async () => {
    const ev = { ...baseEvent, headers: { 'x-api-key': 'wrong' } };
    const out = await handler(ev as any);
    expect(out.policyDocument.Statement[0].Effect).toBe('Deny');
  });

  test('Header is case-insensitive', async () => {
    const ev = { ...baseEvent, headers: { 'X-Api-Key': 'expected-key' } };
    const out = await handler(ev as any);
    expect(out.policyDocument.Statement[0].Effect).toBe('Allow');
  });
});
