import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import test from 'node:test';

const protocolUrl = new URL('./protocol.mjs', import.meta.url);

async function loadProtocol() {
  assert.equal(existsSync(protocolUrl), true, 'SSE relay protocol module has not been implemented');
  return import(protocolUrl.href);
}

async function* chunks(...values) {
  for (const value of values) {
    yield Buffer.isBuffer(value) ? value : Buffer.from(value);
  }
}

function parsedEvents(value) {
  return value
    .split(/\r?\n\r?\n/)
    .filter(Boolean)
    .map((frame) => {
      const data = frame
        .split(/\r?\n/)
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).replace(/^ /, ''))
        .join('\n');
      return JSON.parse(data);
    });
}

test('passes AgentCore SSE through without nesting it in another data frame', async () => {
  const { forwardAgentResponse } = await loadProtocol();
  const writes = [];
  await forwardAgentResponse(
    {
      contentType: 'text/event-stream',
      response: chunks('data: {"type":"text","text":"Hel', 'lo"}\n\n'),
    },
    (value) => writes.push(value),
  );

  assert.equal(writes.join(''), 'data: {"type":"text","text":"Hello"}\n\n');
  assert.doesNotMatch(writes.join(''), /data: data:/);
});

test('normalizes a legacy JSON-string response into a structured text event', async () => {
  const { forwardAgentResponse } = await loadProtocol();
  const writes = [];
  await forwardAgentResponse(
    {
      contentType: 'application/json',
      response: chunks('"Hello from ', 'the copilot"'),
    },
    (value) => writes.push(value),
  );

  assert.deepEqual(JSON.parse(writes.join('').slice(6, -2)), {
    type: 'text',
    text: 'Hello from the copilot',
  });
});

test('forwards each structured object unchanged in SSE and JSON upstream modes', async () => {
  const { forwardAgentResponse, sseEvent } = await loadProtocol();
  const events = [
    {
      type: 'run_spec',
      execution_id: 'run-1',
      spec_hash: 'c'.repeat(64),
      run_spec: { horizon: 252 },
    },
    {
      type: 'exposure_result',
      execution_id: 'run-1',
      spec_hash: 'c'.repeat(64),
      scenario_role: 'baseline',
      terminal: {
        date: '2023-09-19',
        ee: 450586.45,
        pfe_975: 4901670.11,
        es_975: 5828331.63,
      },
    },
    {
      type: 'diagnostics',
      execution_id: 'run-1',
      spec_hash: 'c'.repeat(64),
      diagnostics_uri: 's3://chronos-data/runs/run-1/diagnostics.json',
      diagnostics: {
        attribution: { distribution_count: 5 },
        note: 'line one\nline two',
      },
    },
  ];

  for (const event of events) {
    const sseWrites = [];
    await forwardAgentResponse(
      {
        contentType: 'text/event-stream',
        response: chunks(sseEvent(event)),
      },
      (value) => sseWrites.push(value),
    );
    assert.deepEqual(parsedEvents(sseWrites.join('')), [event]);
    assert.doesNotMatch(sseWrites.join(''), /data: data:/);

    const jsonWrites = [];
    await forwardAgentResponse(
      {
        contentType: 'application/json',
        response: chunks(JSON.stringify(event)),
      },
      (value) => jsonWrites.push(value),
    );
    assert.deepEqual(parsedEvents(jsonWrites.join('')), [event]);
  }
});

test('handles byte-split UTF-8, LF and CRLF frames, and a trailing frame', async () => {
  const { forwardAgentResponse } = await loadProtocol();
  const first = 'data: {"type":"text","text":"café"}\r\n\r\n';
  const second = 'data: {"type":"tool","status":"running"}\n\n';
  const third = 'data: {"type":"diagnostics","diagnostics":{"currency":"€"}}';
  const upstream = Buffer.from(first + second + third);
  const writes = [];

  await forwardAgentResponse(
    {
      contentType: 'text/event-stream',
      response: chunks(...Array.from(upstream, (byte) => Buffer.from([byte]))),
    },
    (value) => writes.push(value),
  );

  assert.deepEqual(parsedEvents(writes.join('')), [
    { type: 'text', text: 'café' },
    { type: 'tool', status: 'running' },
    { type: 'diagnostics', diagnostics: { currency: '€' } },
  ]);
  assert.match(writes.join(''), /\n\n$/);
});

test('keeps exactly one upstream done as the final successful frame', async () => {
  const { forwardAgentResponse } = await loadProtocol();
  const writes = [];

  const outcome = await forwardAgentResponse(
    {
      contentType: 'text/event-stream',
      response: chunks(
        'data: {"type":"text","text":"before"}\n\n',
        'data: {"type":"done"}\n\n',
        'data: {"type":"text","text":"after"}\n\n',
        'data: {"type":"done"}\n\n',
      ),
    },
    (value) => writes.push(value),
  );

  assert.deepEqual(parsedEvents(writes.join('')), [
    { type: 'text', text: 'before' },
    { type: 'text', text: 'after' },
    { type: 'done' },
  ]);
  assert.deepEqual(outcome, { doneSeen: true, errorSeen: false });
});

test('reports a forwarded structured error without adding success completion', async () => {
  const { forwardAgentResponse } = await loadProtocol();
  const writes = [];
  const error = { type: 'error', message: 'runtime failed' };

  const outcome = await forwardAgentResponse(
    {
      contentType: 'application/json',
      response: chunks(JSON.stringify(error)),
    },
    (value) => writes.push(value),
  );

  assert.deepEqual(parsedEvents(writes.join('')), [error]);
  assert.deepEqual(outcome, { doneSeen: false, errorSeen: true });
});
