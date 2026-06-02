export interface Message {
  role: 'user' | 'assistant' | 'tool';
  content: string;
  turn_id: string;
  tool_name?: string;
}

export interface ExposureMetrics {
  ee: number[];
  pfe_975: number[];
  es_975: number[];
  dates: string[];
}

export class ApiClient {
  constructor(private readonly baseUrl: string, private readonly apiKey: string) {}

  private async req<T>(path: string, init: RequestInit = {}): Promise<T> {
    const url = this.baseUrl.replace(/\/$/, '') + path;
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'x-api-key': this.apiKey,
      ...((init.headers as Record<string, string>) ?? {}),
    };
    const resp = await fetch(url, { ...init, headers });
    if (!resp.ok) {
      const body = await resp.text().catch(() => '');
      throw new Error(`${resp.status}: ${body}`);
    }
    return (await resp.json()) as T;
  }

  createSession() {
    return this.req<{ session_id: string }>('/sessions', { method: 'POST' });
  }

  listMessages(sid: string) {
    return this.req<{ messages: Message[] }>(`/sessions/${sid}/messages`);
  }

  postMessage(sid: string, role: Message['role'], content: string) {
    return this.req<{ turn_id: string }>(`/sessions/${sid}/messages`, {
      method: 'POST',
      body: JSON.stringify({ role, content }),
    });
  }

  invoke(sid: string, prompt: string) {
    return this.req<{ text: string }>('/invoke', {
      method: 'POST',
      body: JSON.stringify({ session_id: sid, prompt }),
    });
  }
}
