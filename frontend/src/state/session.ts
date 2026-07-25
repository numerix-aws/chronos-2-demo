const STORAGE_KEY = 'chronos2-demo-session';

export interface SessionState {
  sessionId: string;
  apiKey: string;
}

function isSessionState(value: unknown): value is SessionState {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record);
  return (
    keys.length === 2 &&
    keys.includes('sessionId') &&
    keys.includes('apiKey') &&
    typeof record.sessionId === 'string' &&
    record.sessionId.trim() !== '' &&
    typeof record.apiKey === 'string' &&
    record.apiKey.trim() !== ''
  );
}

export function loadSession(): SessionState | null {
  const raw = sessionStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    const session = JSON.parse(raw);
    if (isSessionState(session)) return session;
  } catch {
    // Malformed JSON is handled by the same removal below.
  }
  sessionStorage.removeItem(STORAGE_KEY);
  return null;
}

export function saveSession(s: SessionState): void {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(s));
}

export function clearSession(): void {
  sessionStorage.removeItem(STORAGE_KEY);
}
