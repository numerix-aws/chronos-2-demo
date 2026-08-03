export type ScenarioRole = 'baseline' | 'chronos_only' | 'augmented';

export type TerminalExposure = {
  date: string;
  ee: number;
  pfe_975: number;
  es_975: number;
};

export type RunSpecEvent = {
  type: 'run_spec';
  executionId: string;
  specHash: string;
  runSpec: Record<string, unknown>;
};

export type ExposureResultEvent = {
  type: 'exposure_result';
  executionId: string;
  specHash: string;
  scenarioRole: ScenarioRole;
  source: string;
  metricsUri: string;
  metricsSha256: string;
  terminal: TerminalExposure;
};

export type DiagnosticsEvent = {
  type: 'diagnostics';
  executionId: string;
  specHash: string;
  diagnosticsUri: string;
  diagnosticsSha256: string;
  diagnostics: Record<string, unknown>;
};

export type StreamEvent =
  | { type: 'chunk'; text: string }
  | {
      type: 'tool';
      toolUseId: string;
      name: string;
      status: 'running' | 'done' | 'failed';
      input?: unknown;
      result?: unknown;
    }
  | RunSpecEvent
  | ExposureResultEvent
  | DiagnosticsEvent
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

function decodeAgentResponse(raw: string): string {
  try {
    const decoded: unknown = JSON.parse(raw);
    return typeof decoded === 'string' ? decoded : raw;
  } catch {
    return raw;
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function decodeStructuredEvent(raw: string): StreamEvent | null {
  let decoded: unknown;
  try {
    decoded = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!decoded || typeof decoded !== 'object' || Array.isArray(decoded)) return null;
  const event = decoded as Record<string, unknown>;
  if (
    event.type === 'run_spec' &&
    typeof event.execution_id === 'string' &&
    typeof event.spec_hash === 'string' &&
    asRecord(event.run_spec)
  ) {
    return {
      type: 'run_spec',
      executionId: event.execution_id,
      specHash: event.spec_hash,
      runSpec: event.run_spec as Record<string, unknown>,
    };
  }
  if (
    event.type === 'exposure_result' &&
    typeof event.execution_id === 'string' &&
    typeof event.spec_hash === 'string' &&
    (event.scenario_role === 'baseline' ||
      event.scenario_role === 'chronos_only' ||
      event.scenario_role === 'augmented') &&
    typeof event.metrics_uri === 'string' &&
    typeof event.metrics_sha256 === 'string' &&
    asRecord(event.terminal)
  ) {
    const terminal = event.terminal as Record<string, unknown>;
    if (
      typeof terminal.date === 'string' &&
      typeof terminal.ee === 'number' &&
      typeof terminal.pfe_975 === 'number' &&
      typeof terminal.es_975 === 'number'
    ) {
      return {
        type: 'exposure_result',
        executionId: event.execution_id,
        specHash: event.spec_hash,
        scenarioRole: event.scenario_role,
        source: String(event.source),
        metricsUri: event.metrics_uri,
        metricsSha256: event.metrics_sha256,
        terminal: terminal as TerminalExposure,
      };
    }
  }
  if (
    event.type === 'diagnostics' &&
    typeof event.execution_id === 'string' &&
    typeof event.spec_hash === 'string' &&
    typeof event.diagnostics_uri === 'string' &&
    typeof event.diagnostics_sha256 === 'string' &&
    asRecord(event.diagnostics)
  ) {
    return {
      type: 'diagnostics',
      executionId: event.execution_id,
      specHash: event.spec_hash,
      diagnosticsUri: event.diagnostics_uri,
      diagnosticsSha256: event.diagnostics_sha256,
      diagnostics: event.diagnostics as Record<string, unknown>,
    };
  }
  if (event.type === 'text' && typeof event.text === 'string') {
    return { type: 'chunk', text: event.text };
  }
  if (
    event.type === 'tool' &&
    typeof event.tool_use_id === 'string' &&
    typeof event.name === 'string' &&
    (event.status === 'running' || event.status === 'done' || event.status === 'failed')
  ) {
    return {
      type: 'tool',
      toolUseId: event.tool_use_id,
      name: event.name,
      status: event.status,
      ...('input' in event ? { input: event.input } : {}),
      ...('result' in event ? { result: event.result } : {}),
    };
  }
  if (event.type === 'done') return { type: 'done' };
  if (event.type === 'error' && typeof event.message === 'string') {
    return { type: 'error', message: event.message };
  }
  if (typeof event.error === 'string') {
    return { type: 'error', message: event.error };
  }
  return null;
}

export async function* parseSseStream(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<StreamEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  let encodedResponse: string | null = null;
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
        if (encodedResponse !== null) {
          yield { type: 'chunk', text: decodeAgentResponse(encodedResponse) };
        }
        yield { type: 'done' };
        return;
      }
      if (parsed.data.startsWith('[ERROR] ')) {
        yield { type: 'error', message: parsed.data.slice(8) };
        return;
      }
      const structured = decodeStructuredEvent(parsed.data);
      if (structured) {
        yield structured;
        if (structured.type === 'done' || structured.type === 'error') return;
        continue;
      }
      if (encodedResponse !== null) {
        encodedResponse += parsed.data;
        continue;
      }
      if (/^\s*"/.test(parsed.data)) {
        encodedResponse = parsed.data;
        continue;
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
  if (!resp.ok) {
    if (resp.status === 401 || resp.status === 403) {
      throw new Error(`${resp.status}`);
    }
    yield { type: 'error', message: `HTTP ${resp.status}` };
    return;
  }
  if (!resp.body) {
    yield { type: 'error', message: `${resp.status}` };
    return;
  }
  yield* parseSseStream(resp.body);
}
