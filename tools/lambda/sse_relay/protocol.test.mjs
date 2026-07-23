import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
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

function immediate() {
  return new Promise((resolve) => setImmediate(resolve));
}

class FakeResponseStream extends EventEmitter {
  constructor({ backpressureAt = [], failContentType = false } = {}) {
    super();
    this.backpressureAt = new Set(backpressureAt);
    this.failContentType = failContentType;
    this.contentTypes = [];
    this.writes = [];
    this.endCount = 0;
  }

  setContentType(value) {
    if (this.failContentType) throw new Error('content type failed');
    this.contentTypes.push(value);
  }

  write(value) {
    this.writes.push(value);
    return !this.backpressureAt.has(this.writes.length);
  }

  end() {
    this.endCount += 1;
  }
}

function validRequest() {
  return {
    headers: { 'x-api-key': 'secret' },
    queryStringParameters: { session_id: 'session-1', prompt: 'price it' },
  };
}

function relayDependencies(overrides = {}) {
  let intervalCallback = null;
  const state = {
    cleared: [],
    get intervalCallback() {
      return intervalCallback;
    },
  };
  const dependencies = {
    getApiKey: async () => 'secret',
    invokeAgent: async () => ({
      contentType: 'text/event-stream',
      response: chunks('data: {"type":"text","text":"ok"}\n\n'),
    }),
    setIntervalFn(callback) {
      intervalCallback = callback;
      return 'heartbeat-handle';
    },
    clearIntervalFn(handle) {
      state.cleared.push(handle);
    },
    ...overrides,
  };
  return { dependencies, state };
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

test('keeps exactly one upstream error as the final terminal frame', async () => {
  const { forwardAgentResponse } = await loadProtocol();
  const writes = [];

  const outcome = await forwardAgentResponse(
    {
      contentType: 'text/event-stream',
      response: chunks(
        'data: {"type":"error","message":"first"}\n\n',
        'data: {"type":"text","text":"after"}\n\n',
        'data: {"type":"error","message":"duplicate"}\n\n',
        'data: {"type":"done"}\n\n',
      ),
    },
    (value) => writes.push(value),
  );

  assert.deepEqual(parsedEvents(writes.join('')), [
    { type: 'text', text: 'after' },
    { type: 'error', message: 'first' },
  ]);
  assert.deepEqual(outcome, { doneSeen: true, errorSeen: true });
});

test('sniffs absent or generic content type as native multi-frame SSE', async () => {
  const { forwardAgentResponse } = await loadProtocol();
  const inputs = [
    {
      response: chunks(
        ...Array.from(
          Buffer.from(
            'event: message\r\nid: 1\r\ndata: {"type":"text","text":"café"}\r\n\r\n'
            + ': source\nretry: 1000\ndata: {"type":"diagnostics","value":"€"}\n\n'
            + 'data: {"type":"done"}\n\n',
          ),
          (byte) => Buffer.from([byte]),
        ),
      ),
    },
    {
      contentType: 'application/octet-stream',
      response: chunks(
        'data: {"type":"text","text":"one"}\n\n',
        'data: {"type":"done"}\n\n',
      ),
    },
  ];

  for (const response of inputs) {
    const writes = [];
    const outcome = await forwardAgentResponse(
      response,
      (value) => writes.push(value),
    );

    assert.equal(parsedEvents(writes.join('')).at(-1).type, 'done');
    assert.equal(parsedEvents(writes.join('')).filter((event) => event.type === 'done').length, 1);
    assert.deepEqual(outcome, { doneSeen: true, errorSeen: false });
    assert.doesNotMatch(writes.join(''), /\{"type":"text","text":"data:/);
  }
});

test('sniffs and forwards the first absent-type SSE frame before upstream EOF', async () => {
  const { forwardAgentResponse } = await loadProtocol();
  let releaseUpstream;
  const upstreamReleased = new Promise((resolve) => {
    releaseUpstream = resolve;
  });
  async function* delayedSse() {
    yield Buffer.from('data: {"type":"text","text":"first"}\n\n');
    await upstreamReleased;
    yield Buffer.from('data: {"type":"done"}\n\n');
  }
  const writes = [];
  let completed = false;

  const forwarding = forwardAgentResponse(
    { response: delayedSse() },
    (frame) => writes.push(frame),
  ).then(() => {
    completed = true;
  });

  await immediate();
  assert.deepEqual(parsedEvents(writes.join('')), [
    { type: 'text', text: 'first' },
  ]);
  assert.equal(completed, false);
  releaseUpstream();
  await forwarding;
  assert.equal(parsedEvents(writes.join('')).at(-1).type, 'done');
});

test('keeps absent content type JSON object and string fallbacks', async () => {
  const { forwardAgentResponse } = await loadProtocol();
  const values = [
    { type: 'run_spec', execution_id: 'run-1' },
    'plain café text',
  ];

  for (const value of values) {
    const raw = Buffer.from(JSON.stringify(value));
    const writes = [];
    await forwardAgentResponse(
      {
        response: chunks(...Array.from(raw, (byte) => Buffer.from([byte]))),
      },
      (frame) => writes.push(frame),
    );

    assert.deepEqual(parsedEvents(writes.join('')), [
      typeof value === 'string' ? { type: 'text', text: value } : value,
    ]);
  }
});

test('does not misclassify an invalid SSE-like prefix', async () => {
  const { forwardAgentResponse } = await loadProtocol();
  const raw = 'data: looks possible\nnot-a-field: no\n\nplain text';
  const writes = [];

  await forwardAgentResponse(
    { response: chunks(raw.slice(0, 12), raw.slice(12)) },
    (frame) => writes.push(frame),
  );

  assert.deepEqual(parsedEvents(writes.join('')), [{
    type: 'text',
    text: raw,
  }]);
});

test('awaits each forwarded write before emitting the next frame', async () => {
  const { forwardAgentResponse } = await loadProtocol();
  const writes = [];
  let releaseFirst;
  const firstWrite = new Promise((resolve) => {
    releaseFirst = resolve;
  });
  let completed = false;

  const forwarding = forwardAgentResponse(
    {
      contentType: 'text/event-stream',
      response: chunks(
        'data: {"type":"text","text":"one"}\n\n'
        + 'data: {"type":"text","text":"two"}\n\n',
      ),
    },
    (frame) => {
      writes.push(frame);
      return writes.length === 1 ? firstWrite : Promise.resolve();
    },
  ).then(() => {
    completed = true;
  });

  await immediate();
  assert.equal(writes.length, 1);
  assert.equal(completed, false);
  releaseFirst();
  await forwarding;
  assert.equal(writes.length, 2);
});

test('relay cleanup covers secret, authorization, and setup failures', async () => {
  const { handleRelayRequest } = await loadProtocol();
  const cases = [
    {
      stream: new FakeResponseStream(),
      event: validRequest(),
      overrides: { getApiKey: async () => { throw new Error('secret failed'); } },
      expectedType: 'text/plain',
      expectedWrite: 'error: secret failed',
    },
    {
      stream: new FakeResponseStream(),
      event: { ...validRequest(), headers: { 'x-api-key': 'wrong' } },
      overrides: {},
      expectedType: 'text/plain',
      expectedWrite: 'unauthorized',
    },
    {
      stream: new FakeResponseStream({ failContentType: true }),
      event: validRequest(),
      overrides: {},
      expectedType: null,
      expectedWrite: null,
    },
  ];

  for (const item of cases) {
    let invoked = false;
    const { dependencies, state } = relayDependencies({
      invokeAgent: async () => {
        invoked = true;
        throw new Error('must not invoke');
      },
      ...item.overrides,
    });

    await handleRelayRequest(item.event, item.stream, dependencies);

    assert.equal(item.stream.endCount, 1);
    assert.equal(invoked, false);
    assert.deepEqual(state.cleared, []);
    if (item.expectedType !== null) {
      assert.deepEqual(item.stream.contentTypes, [item.expectedType]);
    }
    if (item.expectedWrite !== null) {
      assert.equal(item.stream.writes.join(''), item.expectedWrite);
    }
  }
});

test('relay serializes heartbeat and frames behind drain before ending', async () => {
  const { handleRelayRequest } = await loadProtocol();
  const stream = new FakeResponseStream({ backpressureAt: [2] });
  const { dependencies, state } = relayDependencies({
    invokeAgent: async () => ({
      contentType: 'text/event-stream',
      response: chunks(
        'data: {"type":"text","text":"one"}\n\n'
        + 'data: {"type":"text","text":"two"}\n\n',
      ),
    }),
  });

  const handling = handleRelayRequest(validRequest(), stream, dependencies);
  while (stream.writes.length < 2) await immediate();
  state.intervalCallback();
  await immediate();

  assert.equal(stream.writes.length, 2);
  assert.equal(stream.endCount, 0);
  stream.emit('drain');
  await handling;

  assert.deepEqual(stream.writes, [
    ': connected\n\n',
    'data: {"type":"text","text":"one"}\n\n',
    ': keepalive\n\n',
    'data: {"type":"text","text":"two"}\n\n',
    'data: {"type":"done"}\n\n',
  ]);
  assert.deepEqual(state.cleared, ['heartbeat-handle']);
  assert.equal(stream.endCount, 1);
});

test('relay emits structured AgentCore errors and stops heartbeat', async () => {
  const { handleRelayRequest } = await loadProtocol();
  const stream = new FakeResponseStream();
  const { dependencies, state } = relayDependencies({
    invokeAgent: async () => {
      throw new Error('AgentCore failed');
    },
  });

  await handleRelayRequest(validRequest(), stream, dependencies);

  assert.deepEqual(stream.writes, [
    ': connected\n\n',
    'data: {"type":"error","message":"AgentCore failed"}\n\n',
  ]);
  assert.deepEqual(state.cleared, ['heartbeat-handle']);
  assert.equal(stream.endCount, 1);
});

test('relay does not hang when a backpressured stream closes or errors', async () => {
  const { handleRelayRequest } = await loadProtocol();
  for (const signal of ['close', 'error']) {
    const stream = new FakeResponseStream({ backpressureAt: [1] });
    const { dependencies } = relayDependencies();
    const handling = handleRelayRequest(validRequest(), stream, dependencies);

    while (stream.writes.length < 1) await immediate();
    if (signal === 'error') {
      stream.emit('error', new Error('stream failed'));
    } else {
      stream.emit('close');
    }
    await Promise.race([
      handling,
      new Promise((_, reject) => setTimeout(
        () => reject(new Error(`relay hung after ${signal}`)),
        250,
      )),
    ]);

    assert.equal(stream.endCount, 1);
  }
});
