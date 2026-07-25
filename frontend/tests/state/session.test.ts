import { beforeEach, describe, expect, it } from 'vitest';
import { clearSession, loadSession, saveSession } from '../../src/state/session';

describe('browser session state', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it('persists a session only for the current browser tab', () => {
    saveSession({ sessionId: 'session-1', apiKey: 'runtime-code' });

    expect(loadSession()).toEqual({ sessionId: 'session-1', apiKey: 'runtime-code' });
    expect(localStorage.getItem('chronos2-demo-session')).toBeNull();
  });

  it('clears the saved browser session', () => {
    saveSession({ sessionId: 'session-1', apiKey: 'runtime-code' });
    clearSession();

    expect(loadSession()).toBeNull();
  });

  it.each([
    ['malformed JSON', '{'],
    ['scalar string', JSON.stringify('session')],
    ['scalar number', JSON.stringify(1)],
    ['array', JSON.stringify([])],
    ['missing api key', JSON.stringify({ sessionId: 'session-1' })],
    ['missing session id', JSON.stringify({ apiKey: 'runtime-code' })],
    ['empty session id', JSON.stringify({ sessionId: '', apiKey: 'runtime-code' })],
    ['whitespace api key', JSON.stringify({ sessionId: 'session-1', apiKey: '   ' })],
    ['wrong session id type', JSON.stringify({ sessionId: 1, apiKey: 'runtime-code' })],
    ['wrong api key type', JSON.stringify({ sessionId: 'session-1', apiKey: false })],
    ['extra key', JSON.stringify({ sessionId: 'session-1', apiKey: 'runtime-code', extra: true })],
  ])('removes %s session storage', (_label, raw) => {
    sessionStorage.setItem('chronos2-demo-session', raw);

    expect(loadSession()).toBeNull();
    expect(sessionStorage.getItem('chronos2-demo-session')).toBeNull();
  });

  it('loads an exact valid session object', () => {
    sessionStorage.setItem(
      'chronos2-demo-session',
      JSON.stringify({ sessionId: 'session-1', apiKey: 'runtime-code' }),
    );

    expect(loadSession()).toEqual({ sessionId: 'session-1', apiKey: 'runtime-code' });
  });
});
