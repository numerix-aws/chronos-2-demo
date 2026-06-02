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
