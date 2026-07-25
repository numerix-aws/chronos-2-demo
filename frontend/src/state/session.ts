const STORAGE_KEY = 'chronos2-demo-session';

export interface SessionState {
  sessionId: string;
  apiKey: string;
}

export function loadSession(): SessionState | null {
  const raw = sessionStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as SessionState;
  } catch {
    return null;
  }
}

export function saveSession(s: SessionState): void {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(s));
}

export function clearSession(): void {
  sessionStorage.removeItem(STORAGE_KEY);
}
