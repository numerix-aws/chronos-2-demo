import { afterEach, describe, it, expect, vi } from 'vitest';
import { parseSseFrame, parseSseStream, streamAgent } from '../../src/api/stream';

afterEach(() => {
  vi.unstubAllGlobals();
});

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

  it('decodes a JSON-string AgentCore response split across SSE frames', async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('data: "# Chronos-2 Demo\\n\\nHello from the \n\n'));
        controller.enqueue(encoder.encode('data: copilot."\n\n'));
        controller.enqueue(encoder.encode('data: [DONE]\n\n'));
        controller.close();
      },
    });

    const events: any[] = [];
    for await (const ev of parseSseStream(body)) events.push(ev);
    expect(events).toEqual([
      { type: 'chunk', text: '# Chronos-2 Demo\n\nHello from the copilot.' },
      { type: 'done' },
    ]);
  });

  it('decodes structured text, tool lifecycle, and completion events', async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            'data: {"type":"text","text":"Starting"}\n\n' +
              'data: {"type":"tool","tool_use_id":"tool-1","name":"load_data","status":"running","input":{}}\n\n',
          ),
        );
        controller.enqueue(
          encoder.encode(
            'data: {"type":"tool","tool_use_id":"tool-1","name":"load_data","status":"done","result":{"status":"ok","result":{"panel_uri":"s3://panel"}}}\n\n' +
              'data: {"type":"done"}\n\n',
          ),
        );
        controller.close();
      },
    });

    const events: any[] = [];
    for await (const ev of parseSseStream(body)) events.push(ev);
    expect(events).toEqual([
      { type: 'chunk', text: 'Starting' },
      {
        type: 'tool',
        toolUseId: 'tool-1',
        name: 'load_data',
        status: 'running',
        input: {},
      },
      {
        type: 'tool',
        toolUseId: 'tool-1',
        name: 'load_data',
        status: 'done',
        result: { status: 'ok', result: { panel_uri: 's3://panel' } },
      },
      { type: 'done' },
    ]);
  });

  it('decodes split quantitative events and multiple events in one network chunk', async () => {
    const encoder = new TextEncoder();
    const runSpec =
      '{"type":"run_spec","execution_id":"run-1","spec_hash":"hash-1","run_spec":{"profile":"stage_safe_headline_v1"}}';
    const exposure =
      '{"type":"exposure_result","execution_id":"run-1","spec_hash":"hash-1","scenario_role":"augmented","source":"blended","metrics_uri":"s3://metrics","metrics_sha256":"metrics-1","terminal":{"date":"2023-09-19","ee":1,"pfe_975":2,"es_975":3}}';
    const diagnostics =
      '{"type":"diagnostics","execution_id":"run-1","spec_hash":"hash-1","diagnostics_uri":"s3://diagnostics","diagnostics_sha256":"diagnostics-1","diagnostics":{"attribution":{}}}';
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(`data: ${runSpec.slice(0, 58)}`));
        controller.enqueue(encoder.encode(`${runSpec.slice(58)}\n\ndata: ${exposure}\n\ndata: ${diagnostics}\n\n`));
        controller.enqueue(encoder.encode('data: {"type":"done"}\n\n'));
        controller.close();
      },
    });

    const events: unknown[] = [];
    for await (const event of parseSseStream(body)) events.push(event);

    expect(events).toEqual([
      {
        type: 'run_spec',
        executionId: 'run-1',
        specHash: 'hash-1',
        runSpec: { profile: 'stage_safe_headline_v1' },
      },
      {
        type: 'exposure_result',
        executionId: 'run-1',
        specHash: 'hash-1',
        scenarioRole: 'augmented',
        source: 'blended',
        metricsUri: 's3://metrics',
        metricsSha256: 'metrics-1',
        terminal: { date: '2023-09-19', ee: 1, pfe_975: 2, es_975: 3 },
      },
      {
        type: 'diagnostics',
        executionId: 'run-1',
        specHash: 'hash-1',
        diagnosticsUri: 's3://diagnostics',
        diagnosticsSha256: 'diagnostics-1',
        diagnostics: { attribution: {} },
      },
      { type: 'done' },
    ]);
  });
});

describe('streamAgent', () => {
  it.each([401, 403])('throws an HTTP %i response for the caller to handle', async (status) => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('expired access code', { status })),
    );

    const iterator = streamAgent('https://stream.example.com', 'stale-key', 'session-1', 'run');

    await expect(iterator.next()).rejects.toThrow(`${status}: expired access code`);
  });
});
