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
});
