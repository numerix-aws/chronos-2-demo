# Plan B — Part 7 (Stage 7: Cloudscape SPA)

> Continuation of `2026-05-22-plan-b-ux-agent.md`. Re-read the Executor's Contract there before starting.

---

## Stage 7 — Cloudscape SPA

### Task 19: Bootstrap the React + Vite + Cloudscape app

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/state/session.ts`
- Create: `frontend/tests/App.test.tsx`
- Create: `frontend/tests/setup.ts`
- Create: `frontend/.gitignore`

This task has **no failing test in the strict TDD sense for bootstrap files** (Vite/Tsconfig). The `App.test.tsx` test does follow TDD.

- [ ] **Step 1: Create `frontend/package.json`**

```json
{
  "name": "chronos2-demo-frontend",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "@cloudscape-design/components": "^3.0.0",
    "@cloudscape-design/global-styles": "^1.0.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.4.0",
    "@testing-library/react": "^14.2.0",
    "@testing-library/user-event": "^14.5.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "happy-dom": "^14.0.0",
    "typescript": "^5.4.0",
    "vite": "^5.2.0",
    "vitest": "^1.6.0"
  }
}
```

- [ ] **Step 2: Create `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src", "tests"]
}
```

- [ ] **Step 3: Create `frontend/vite.config.ts`**

```typescript
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'happy-dom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
  },
});
```

- [ ] **Step 4: Create `frontend/tests/setup.ts`**

```typescript
import '@testing-library/jest-dom/vitest';
```

- [ ] **Step 5: Create `frontend/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Numerix × Chronos-2</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 6: Create `frontend/src/state/session.ts`**

```typescript
const STORAGE_KEY = 'chronos2-demo-session';

export interface SessionState {
  sessionId: string;
  apiKey: string;
}

export function loadSession(): SessionState | null {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as SessionState;
  } catch {
    return null;
  }
}

export function saveSession(s: SessionState): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
}

export function clearSession(): void {
  localStorage.removeItem(STORAGE_KEY);
}
```

- [ ] **Step 7: Write the failing App test**

`frontend/tests/App.test.tsx`:
```typescript
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { App } from '../src/App';

describe('App', () => {
  it('renders the Numerix × Chronos-2 app shell', () => {
    render(<App />);
    expect(screen.getByText(/Numerix/)).toBeInTheDocument();
    expect(screen.getByText(/Chronos-2/)).toBeInTheDocument();
  });

  it('shows a sidebar containing the chat panel and what-if form regions', () => {
    render(<App />);
    expect(screen.getByRole('region', { name: /chat/i })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /what-if/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 8: Run, confirm fail**

```bash
cd frontend && npm install && npm test
```

Expected: FAIL — `Cannot find module '../src/App'`.

- [ ] **Step 9: Implement `frontend/src/App.tsx`**

```typescript
import { AppLayout, ContentLayout, Header, SpaceBetween } from '@cloudscape-design/components';
import '@cloudscape-design/global-styles/index.css';

export function App() {
  return (
    <AppLayout
      navigationHide
      toolsHide
      content={
        <ContentLayout
          header={
            <Header variant="h1" description="Chronos-2 augmenting the Numerix Monte Carlo">
              Numerix × Chronos-2 Demo
            </Header>
          }
        >
          <SpaceBetween size="l">
            <section aria-label="Chat" role="region">
              {/* ChatPanel mounts here in Task 20 */}
              <Header variant="h2">Conversation</Header>
            </section>
            <section aria-label="What-if" role="region">
              {/* WhatIfForm mounts here in Task 22 */}
              <Header variant="h2">What-if parameters</Header>
            </section>
          </SpaceBetween>
        </ContentLayout>
      }
    />
  );
}
```

- [ ] **Step 10: Implement `frontend/src/main.tsx`**

```typescript
import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './App';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

- [ ] **Step 11: Create `frontend/.gitignore`**

```gitignore
node_modules/
dist/
.vite/
*.tsbuildinfo
.DS_Store
```

- [ ] **Step 12: Run tests, confirm pass**

```bash
cd frontend && npm test
```

Expected: 2 passed.

- [ ] **Step 13: Smoke `npm run build`**

```bash
cd frontend && npm run build
```

Expected: `dist/` directory created with `index.html` + assets.

- [ ] **Step 14: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): bootstrap React + Vite + Cloudscape SPA shell

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 20: API client + SSE consumer

**Files:**
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/stream.ts`
- Create: `frontend/tests/api/client.test.ts`
- Create: `frontend/tests/api/stream.test.ts`

`client.ts` is a thin `fetch` wrapper that injects `x-api-key` and parses JSON responses. `stream.ts` consumes the Function URL SSE endpoint via `EventSource` (or a `fetch+ReadableStream` fallback for header-based auth) and emits `{type: "chunk", text}` / `{type: "done"}` / `{type: "error"}` events.

> **Why fetch+ReadableStream, not EventSource:** browsers' `EventSource` cannot send custom headers (no `x-api-key`). Function URL doesn't accept query-string auth secrets safely. So we manually parse SSE off a streaming `fetch`.

- [ ] **Step 1: Write the failing client test**

`frontend/tests/api/client.test.ts`:
```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ApiClient } from '../../src/api/client';

describe('ApiClient', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });

  it('attaches x-api-key header to every request', async () => {
    (global.fetch as any).mockResolvedValue({
      ok: true,
      json: async () => ({ session_id: 'abc' }),
    });
    const c = new ApiClient('https://api.example/', 'KEY');
    await c.createSession();
    const [, init] = (global.fetch as any).mock.calls[0];
    expect(init.headers['x-api-key']).toBe('KEY');
  });

  it('throws on non-ok response with body text', async () => {
    (global.fetch as any).mockResolvedValue({
      ok: false,
      status: 401,
      text: async () => 'unauthorized',
    });
    const c = new ApiClient('https://api.example/', 'BAD');
    await expect(c.createSession()).rejects.toThrow(/401/);
  });

  it('listMessages GETs the right URL', async () => {
    (global.fetch as any).mockResolvedValue({ ok: true, json: async () => ({ messages: [] }) });
    const c = new ApiClient('https://api.example/', 'K');
    await c.listMessages('SID');
    expect((global.fetch as any).mock.calls[0][0]).toBe(
      'https://api.example/sessions/SID/messages',
    );
  });
});
```

- [ ] **Step 2: Run, confirm fail**

```bash
cd frontend && npm test -- client.test
```

Expected: FAIL — `Cannot find module '../../src/api/client'`.

- [ ] **Step 3: Implement `frontend/src/api/client.ts`**

```typescript
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
```

- [ ] **Step 4: Run, confirm pass**

```bash
cd frontend && npm test -- client.test
```

Expected: 3 passed.

- [ ] **Step 5: Write the failing stream test**

`frontend/tests/api/stream.test.ts`:
```typescript
import { describe, it, expect } from 'vitest';
import { parseSseFrame, parseSseStream } from '../../src/api/stream';

describe('parseSseFrame', () => {
  it('extracts a single-line data event', () => {
    expect(parseSseFrame('data: hello\n\n')).toEqual({ data: 'hello' });
  });

  it('joins multi-line data events with newlines', () => {
    expect(parseSseFrame('data: line1\ndata: line2\n\n')).toEqual({
      data: 'line1\nline2',
    });
  });

  it('returns null for incomplete frames', () => {
    expect(parseSseFrame('data: partial')).toBeNull();
  });
});

describe('parseSseStream', () => {
  it('emits chunk events and a done sentinel', async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('data: hello\n\n'));
        controller.enqueue(encoder.encode('data: [DONE]\n\n'));
        controller.close();
      },
    });

    const events: any[] = [];
    for await (const ev of parseSseStream(body)) events.push(ev);
    expect(events).toEqual([
      { type: 'chunk', text: 'hello' },
      { type: 'done' },
    ]);
  });
});
```

- [ ] **Step 6: Run, confirm fail**

```bash
cd frontend && npm test -- stream.test
```

Expected: FAIL — `Cannot find module '../../src/api/stream'`.

- [ ] **Step 7: Implement `frontend/src/api/stream.ts`**

```typescript
export type StreamEvent =
  | { type: 'chunk'; text: string }
  | { type: 'done' }
  | { type: 'error'; message: string };

export function parseSseFrame(raw: string): { data: string } | null {
  if (!raw.endsWith('\n\n')) return null;
  const lines = raw.slice(0, -2).split('\n');
  const data = lines
    .filter((l) => l.startsWith('data: '))
    .map((l) => l.slice(6))
    .join('\n');
  return { data };
}

export async function* parseSseStream(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<StreamEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, idx + 2);
      buf = buf.slice(idx + 2);
      const parsed = parseSseFrame(frame);
      if (!parsed) continue;
      if (parsed.data === '[DONE]') {
        yield { type: 'done' };
        return;
      }
      if (parsed.data.startsWith('[ERROR] ')) {
        yield { type: 'error', message: parsed.data.slice(8) };
        return;
      }
      yield { type: 'chunk', text: parsed.data };
    }
  }
}

export async function* streamAgent(
  streamUrl: string,
  apiKey: string,
  sessionId: string,
  prompt: string,
): AsyncGenerator<StreamEvent> {
  const url = `${streamUrl}?session_id=${encodeURIComponent(sessionId)}&prompt=${encodeURIComponent(prompt)}`;
  const resp = await fetch(url, { headers: { 'x-api-key': apiKey } });
  if (!resp.ok || !resp.body) {
    yield { type: 'error', message: `${resp.status}` };
    return;
  }
  yield* parseSseStream(resp.body);
}
```

- [ ] **Step 8: Run, confirm pass**

```bash
cd frontend && npm test
```

Expected: all green.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/api/ frontend/tests/api/
git commit -m "feat(frontend): API client and SSE stream consumer

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 21: ChatPanel + ImageViewer

**Files:**
- Create: `frontend/src/components/ImageViewer.tsx`
- Create: `frontend/src/components/ChatPanel.tsx`
- Create: `frontend/tests/components/ChatPanel.test.tsx`
- Modify: `frontend/src/App.tsx` — mount `ChatPanel`

`ChatPanel` displays a transcript and a `Textarea` + Send button. As the assistant streams tokens, the in-flight bubble grows. When the assistant emits a markdown image link (`![alt](https://…/plot.png)`), `ImageViewer` renders it inline with a captioning fallback. The chat sets `aria-live="polite"` so screen readers announce new tokens.

- [ ] **Step 1: Write the failing ChatPanel test**

`frontend/tests/components/ChatPanel.test.tsx`:
```typescript
import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatPanel } from '../../src/components/ChatPanel';

describe('ChatPanel', () => {
  it('renders prior messages from props', () => {
    render(
      <ChatPanel
        messages={[
          { role: 'user', content: 'hi', turn_id: '1' },
          { role: 'assistant', content: 'hello', turn_id: '2' },
        ]}
        onSend={vi.fn()}
        streaming={false}
      />,
    );
    expect(screen.getByText('hi')).toBeInTheDocument();
    expect(screen.getByText('hello')).toBeInTheDocument();
  });

  it('calls onSend with typed text and clears the input', async () => {
    const onSend = vi.fn();
    render(<ChatPanel messages={[]} onSend={onSend} streaming={false} />);
    const input = screen.getByLabelText(/message/i) as HTMLTextAreaElement;
    await userEvent.type(input, 'run baseline');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));
    expect(onSend).toHaveBeenCalledWith('run baseline');
    await waitFor(() => expect(input.value).toBe(''));
  });

  it('disables the send button while streaming', () => {
    render(<ChatPanel messages={[]} onSend={vi.fn()} streaming={true} />);
    expect(screen.getByRole('button', { name: /send/i })).toBeDisabled();
  });

  it('renders an inline image when assistant content has a markdown image', () => {
    render(
      <ChatPanel
        messages={[
          {
            role: 'assistant',
            content: 'Here is the chart ![pfe](https://example.com/p.png)',
            turn_id: '1',
          },
        ]}
        onSend={vi.fn()}
        streaming={false}
      />,
    );
    const img = screen.getByAltText('pfe') as HTMLImageElement;
    expect(img.src).toBe('https://example.com/p.png');
  });
});
```

- [ ] **Step 2: Run, confirm fail**

```bash
cd frontend && npm test -- ChatPanel
```

Expected: FAIL — `Cannot find module`.

- [ ] **Step 3: Implement `frontend/src/components/ImageViewer.tsx`**

```typescript
interface ImageViewerProps {
  alt: string;
  src: string;
}

export function ImageViewer({ alt, src }: ImageViewerProps) {
  return (
    <figure style={{ margin: 0 }}>
      <img
        src={src}
        alt={alt}
        loading="lazy"
        style={{ maxWidth: '100%', borderRadius: 4, border: '1px solid #ddd' }}
      />
      {alt ? <figcaption style={{ fontSize: 12, color: '#555' }}>{alt}</figcaption> : null}
    </figure>
  );
}
```

- [ ] **Step 4: Implement `frontend/src/components/ChatPanel.tsx`**

```typescript
import { useState, useRef, useEffect, FormEvent } from 'react';
import { Box, Button, SpaceBetween, Textarea } from '@cloudscape-design/components';
import { ImageViewer } from './ImageViewer';
import type { Message } from '../api/client';

interface ChatPanelProps {
  messages: Message[];
  onSend: (text: string) => void;
  streaming: boolean;
}

const IMAGE_RE = /!\[([^\]]*)\]\((https?:[^)]+)\)/g;

function renderContent(content: string): JSX.Element[] {
  const parts: JSX.Element[] = [];
  let last = 0;
  let key = 0;
  for (const m of content.matchAll(IMAGE_RE)) {
    if (m.index === undefined) continue;
    if (m.index > last) {
      parts.push(<span key={key++}>{content.slice(last, m.index)}</span>);
    }
    parts.push(<ImageViewer key={key++} alt={m[1]} src={m[2]} />);
    last = m.index + m[0].length;
  }
  if (last < content.length) parts.push(<span key={key++}>{content.slice(last)}</span>);
  return parts;
}

export function ChatPanel({ messages, onSend, streaming }: ChatPanelProps) {
  const [draft, setDraft] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const t = draft.trim();
    if (!t) return;
    onSend(t);
    setDraft('');
  };

  return (
    <SpaceBetween size="m">
      <div
        ref={scrollRef}
        aria-live="polite"
        style={{ maxHeight: 480, overflowY: 'auto', padding: 8, background: '#fafafa' }}
      >
        {messages.map((m) => (
          <div
            key={m.turn_id}
            style={{
              marginBottom: 12,
              padding: 8,
              background: m.role === 'user' ? '#e7f1ff' : '#fff',
              borderRadius: 4,
              border: '1px solid #e1e4ea',
            }}
          >
            <Box variant="awsui-key-label">{m.role.toUpperCase()}</Box>
            <div style={{ whiteSpace: 'pre-wrap' }}>{renderContent(m.content)}</div>
          </div>
        ))}
      </div>
      <form onSubmit={submit}>
        <SpaceBetween size="xs" direction="vertical">
          <Textarea
            value={draft}
            onChange={({ detail }) => setDraft(detail.value)}
            placeholder="Ask the copilot..."
            ariaLabel="message"
            disabled={streaming}
            rows={3}
          />
          <Button variant="primary" disabled={streaming || !draft.trim()} formAction="submit">
            Send
          </Button>
        </SpaceBetween>
      </form>
    </SpaceBetween>
  );
}
```

- [ ] **Step 5: Mount in `frontend/src/App.tsx`**

Replace the `<section aria-label="Chat">` body with:

```tsx
import { useEffect, useState } from 'react';
import { ChatPanel } from './components/ChatPanel';
import { ApiClient, type Message } from './api/client';
import { streamAgent } from './api/stream';
import { loadSession } from './state/session';

// ...inside App():
const session = loadSession();
const [messages, setMessages] = useState<Message[]>([]);
const [streaming, setStreaming] = useState(false);

const apiBase = import.meta.env.VITE_API_URL as string;
const streamBase = import.meta.env.VITE_STREAM_URL as string;
const client = session ? new ApiClient(apiBase, session.apiKey) : null;

useEffect(() => {
  if (!client || !session) return;
  client.listMessages(session.sessionId).then((r) => setMessages(r.messages));
}, []);

const handleSend = async (text: string) => {
  if (!client || !session) return;
  setStreaming(true);
  setMessages((prev) => [
    ...prev,
    { role: 'user', content: text, turn_id: `local-${Date.now()}` },
  ]);
  let acc = '';
  setMessages((prev) => [
    ...prev,
    { role: 'assistant', content: '', turn_id: `local-asst-${Date.now()}` },
  ]);
  for await (const ev of streamAgent(streamBase, session.apiKey, session.sessionId, text)) {
    if (ev.type === 'chunk') {
      acc += ev.text;
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = { ...next[next.length - 1], content: acc };
        return next;
      });
    } else if (ev.type === 'error') {
      acc += `\n[error: ${ev.message}]`;
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = { ...next[next.length - 1], content: acc };
        return next;
      });
    }
  }
  setStreaming(false);
};
```

And replace the chat region body:
```tsx
<section aria-label="Chat" role="region">
  <Header variant="h2">Conversation</Header>
  <ChatPanel messages={messages} onSend={handleSend} streaming={streaming} />
</section>
```

- [ ] **Step 6: Run tests, confirm pass**

```bash
cd frontend && npm test
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ChatPanel.tsx frontend/src/components/ImageViewer.tsx frontend/tests/components/ChatPanel.test.tsx frontend/src/App.tsx
git commit -m "feat(frontend): chat panel with streaming + inline image rendering

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 22: WhatIfForm (interactive parameter form)

**Files:**
- Create: `frontend/src/components/WhatIfForm.tsx`
- Create: `frontend/tests/components/WhatIfForm.test.tsx`
- Modify: `frontend/src/App.tsx` — mount `WhatIfForm`

The what-if form drives §3 beat 5: the analyst tweaks `as_of_date`, `lookback_days`, `horizon`, `n_paths`, `w_stress` and re-runs the chain. Form submit fires `onApply(params)`, which `App.tsx` turns into a synthetic prompt like `"re-run with w_stress=0.7, as_of=2020-03-15"` so the agent reuses its tool plan rather than getting hand-coded REST calls from the SPA.

- [ ] **Step 1: Write the failing test**

`frontend/tests/components/WhatIfForm.test.tsx`:
```typescript
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { WhatIfForm } from '../../src/components/WhatIfForm';

describe('WhatIfForm', () => {
  it('renders default values', () => {
    render(<WhatIfForm onApply={vi.fn()} disabled={false} />);
    expect((screen.getByLabelText(/w_stress/i) as HTMLInputElement).value).toBe('0.5');
    expect((screen.getByLabelText(/horizon/i) as HTMLInputElement).value).toBe('252');
  });

  it('calls onApply with parsed numeric values', async () => {
    const onApply = vi.fn();
    render(<WhatIfForm onApply={onApply} disabled={false} />);
    await userEvent.clear(screen.getByLabelText(/w_stress/i));
    await userEvent.type(screen.getByLabelText(/w_stress/i), '0.8');
    await userEvent.click(screen.getByRole('button', { name: /apply/i }));
    expect(onApply).toHaveBeenCalledWith(
      expect.objectContaining({ w_stress: 0.8, horizon: 252, n_paths: 2000 }),
    );
  });

  it('rejects w_stress outside [0,1]', async () => {
    const onApply = vi.fn();
    render(<WhatIfForm onApply={onApply} disabled={false} />);
    await userEvent.clear(screen.getByLabelText(/w_stress/i));
    await userEvent.type(screen.getByLabelText(/w_stress/i), '1.5');
    await userEvent.click(screen.getByRole('button', { name: /apply/i }));
    expect(onApply).not.toHaveBeenCalled();
    expect(screen.getByText(/between 0 and 1/i)).toBeInTheDocument();
  });

  it('disables apply when disabled prop is true', () => {
    render(<WhatIfForm onApply={vi.fn()} disabled={true} />);
    expect(screen.getByRole('button', { name: /apply/i })).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run, confirm fail**

```bash
cd frontend && npm test -- WhatIfForm
```

Expected: FAIL — `Cannot find module`.

- [ ] **Step 3: Implement `frontend/src/components/WhatIfForm.tsx`**

```typescript
import { useState, FormEvent } from 'react';
import {
  Button,
  ColumnLayout,
  Form,
  FormField,
  Input,
  SpaceBetween,
} from '@cloudscape-design/components';

export interface WhatIfParams {
  as_of_date: string;
  lookback_days: number;
  horizon: number;
  n_paths: number;
  w_stress: number;
}

interface WhatIfFormProps {
  onApply: (p: WhatIfParams) => void;
  disabled: boolean;
}

const DEFAULTS: WhatIfParams = {
  as_of_date: '2020-03-15',
  lookback_days: 1260,
  horizon: 252,
  n_paths: 2000,
  w_stress: 0.5,
};

export function WhatIfForm({ onApply, disabled }: WhatIfFormProps) {
  const [v, setV] = useState<Record<keyof WhatIfParams, string>>({
    as_of_date: DEFAULTS.as_of_date,
    lookback_days: String(DEFAULTS.lookback_days),
    horizon: String(DEFAULTS.horizon),
    n_paths: String(DEFAULTS.n_paths),
    w_stress: String(DEFAULTS.w_stress),
  });
  const [err, setErr] = useState<string | null>(null);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const lb = parseInt(v.lookback_days, 10);
    const hz = parseInt(v.horizon, 10);
    const np = parseInt(v.n_paths, 10);
    const w = parseFloat(v.w_stress);
    if (!(w >= 0 && w <= 1)) {
      setErr('w_stress must be between 0 and 1');
      return;
    }
    if (!(lb > 0 && hz > 0 && np > 0)) {
      setErr('lookback_days, horizon, n_paths must be positive');
      return;
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(v.as_of_date)) {
      setErr('as_of_date must be YYYY-MM-DD');
      return;
    }
    setErr(null);
    onApply({
      as_of_date: v.as_of_date,
      lookback_days: lb,
      horizon: hz,
      n_paths: np,
      w_stress: w,
    });
  };

  const fld = (key: keyof WhatIfParams, label: string, type = 'text') => (
    <FormField label={label}>
      <Input
        value={v[key]}
        onChange={({ detail }) => setV({ ...v, [key]: detail.value })}
        type={type === 'number' ? 'number' : 'text'}
        ariaLabel={label}
      />
    </FormField>
  );

  return (
    <form onSubmit={submit}>
      <Form
        errorText={err ?? undefined}
        actions={
          <Button variant="primary" disabled={disabled} formAction="submit">
            Apply
          </Button>
        }
      >
        <SpaceBetween size="m">
          <ColumnLayout columns={3}>
            {fld('as_of_date', 'as_of_date')}
            {fld('lookback_days', 'lookback_days', 'number')}
            {fld('horizon', 'horizon', 'number')}
            {fld('n_paths', 'n_paths', 'number')}
            {fld('w_stress', 'w_stress', 'number')}
          </ColumnLayout>
        </SpaceBetween>
      </Form>
    </form>
  );
}
```

- [ ] **Step 4: Mount in `App.tsx` what-if region**

```tsx
import { WhatIfForm, type WhatIfParams } from './components/WhatIfForm';

// ...
const handleApply = (p: WhatIfParams) => {
  const prompt =
    `Re-run the demo with as_of_date=${p.as_of_date}, lookback_days=${p.lookback_days}, ` +
    `horizon=${p.horizon}, n_paths=${p.n_paths}, w_stress=${p.w_stress}. ` +
    `Compare PFE against the previous run and explain the delta.`;
  void handleSend(prompt);
};

// ...replace the what-if region body:
<section aria-label="What-if" role="region">
  <Header variant="h2">What-if parameters</Header>
  <WhatIfForm onApply={handleApply} disabled={streaming} />
</section>
```

- [ ] **Step 5: Run tests, confirm pass**

```bash
cd frontend && npm test
```

Expected: all green (App.test, ChatPanel.test, WhatIfForm.test, client.test, stream.test).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/WhatIfForm.tsx frontend/tests/components/WhatIfForm.test.tsx frontend/src/App.tsx
git commit -m "feat(frontend): what-if parameter form drives synthetic re-run prompt

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

> _Continue with `2026-05-22-plan-b-ux-agent-part-8.md` (Stage 8 — Frontend stack + observability + deploy, Tasks 23–24)._
