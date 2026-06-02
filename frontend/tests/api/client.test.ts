import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ApiClient } from '../../src/api/client';

describe('ApiClient', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn();
  });

  it('attaches x-api-key header to every request', async () => {
    (globalThis.fetch as any).mockResolvedValue({
      ok: true,
      json: async () => ({ session_id: 'abc' }),
    });
    const c = new ApiClient('https://api.example/', 'KEY');
    await c.createSession();
    const [, init] = (globalThis.fetch as any).mock.calls[0];
    expect(init.headers['x-api-key']).toBe('KEY');
  });

  it('throws on non-ok response with body text', async () => {
    (globalThis.fetch as any).mockResolvedValue({
      ok: false,
      status: 401,
      text: async () => 'unauthorized',
    });
    const c = new ApiClient('https://api.example/', 'BAD');
    await expect(c.createSession()).rejects.toThrow(/401/);
  });

  it('listMessages GETs the right URL', async () => {
    (globalThis.fetch as any).mockResolvedValue({ ok: true, json: async () => ({ messages: [] }) });
    const c = new ApiClient('https://api.example/', 'K');
    await c.listMessages('SID');
    expect((globalThis.fetch as any).mock.calls[0][0]).toBe(
      'https://api.example/sessions/SID/messages',
    );
  });
});
