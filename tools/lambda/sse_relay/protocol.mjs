export function sseEvent(event) {
  return `data: ${JSON.stringify(event)}\n\n`;
}

function frameObject(frame) {
  const data = frame
    .split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).replace(/^ /, ''))
    .join('\n');
  if (!data) return null;
  try {
    const value = JSON.parse(data);
    return value && typeof value === 'object' && !Array.isArray(value) ? value : null;
  } catch {
    return null;
  }
}

function nextFrame(buffer) {
  const match = /\r?\n\r?\n/.exec(buffer);
  if (!match) return null;
  const end = match.index + match[0].length;
  return [buffer.slice(0, end), buffer.slice(end)];
}

function validSseFrame(frame) {
  const body = frame.replace(/\r?\n\r?\n$/, '');
  const allowed = new Set(['data', 'event', 'id', 'retry']);
  let recognized = false;
  for (const line of body.split(/\r?\n/)) {
    if (line.startsWith(':')) {
      recognized = true;
      continue;
    }
    const colon = line.indexOf(':');
    const field = colon < 0 ? line : line.slice(0, colon);
    const value = colon < 0 ? '' : line.slice(colon + 1).replace(/^ /, '');
    if (!allowed.has(field)) return false;
    if (field === 'retry' && !/^\d+$/.test(value)) return false;
    recognized = true;
  }
  return recognized;
}

function inspectCompleteFrames(buffer) {
  let scanned = buffer;
  let count = 0;
  let parsed;
  while ((parsed = nextFrame(scanned)) !== null) {
    if (!validSseFrame(parsed[0])) return { count, invalid: true };
    count += 1;
    scanned = parsed[1];
  }
  return { count, invalid: false };
}

async function* decodedChunks(body) {
  const decoder = new TextDecoder();
  for await (const chunk of body) {
    const text = decoder.decode(chunk, { stream: true });
    if (text) yield text;
  }
  const trailing = decoder.decode();
  if (trailing) yield trailing;
}

async function forwardSseText(textChunks, initialBuffer, write) {
  let buffer = initialBuffer;
  let doneFrame = null;
  let errorFrame = null;
  let doneSeen = false;
  let errorSeen = false;

  async function forwardFrame(frame) {
    const event = frameObject(frame);
    if (event?.type === 'done') {
      doneSeen = true;
      if (doneFrame === null) doneFrame = frame;
      return;
    }
    if (event?.type === 'error') {
      errorSeen = true;
      if (errorFrame === null) errorFrame = frame;
      return;
    }
    await write(frame);
  }

  async function flushFrames() {
    let parsed;
    while ((parsed = nextFrame(buffer)) !== null) {
      await forwardFrame(parsed[0]);
      buffer = parsed[1];
    }
  }

  await flushFrames();
  for await (const text of textChunks) {
    buffer += text;
    await flushFrames();
  }
  if (buffer) await forwardFrame(`${buffer}\n\n`);
  if (errorFrame !== null) {
    await write(errorFrame);
  } else if (doneFrame !== null) {
    await write(doneFrame);
  }
  return { doneSeen, errorSeen };
}

async function collectText(textChunks) {
  let raw = '';
  for await (const text of textChunks) raw += text;
  return raw;
}

async function sniffAndForward(textChunks, write) {
  const iterator = textChunks[Symbol.asyncIterator]();
  let buffer = '';
  while (true) {
    const next = await iterator.next();
    if (next.done) return forwardFallback(buffer, write);
    buffer += next.value;
    const inspection = inspectCompleteFrames(buffer);
    if (inspection.invalid) {
      return forwardFallback(
        buffer + await collectText(iterator),
        write,
      );
    }
    if (inspection.count > 0) {
      return forwardSseText(iterator, buffer, write);
    }
  }
}

async function forwardFallback(raw, write) {
  if (!raw) return { doneSeen: false, errorSeen: false };
  let decoded;
  try {
    decoded = JSON.parse(raw);
  } catch {
    decoded = raw;
  }
  const event = typeof decoded === 'string'
    ? { type: 'text', text: decoded }
    : decoded;
  await write(sseEvent(event));
  return {
    doneSeen: event?.type === 'done',
    errorSeen: event?.type === 'error',
  };
}

export async function forwardAgentResponse(response, write) {
  const contentType = String(response.contentType || '').trim().toLowerCase();
  const textChunks = decodedChunks(response.response);
  if (contentType.includes('text/event-stream')) {
    return forwardSseText(textChunks, '', write);
  }

  const shouldSniff = !contentType.includes('json');
  if (shouldSniff) return sniffAndForward(textChunks, write);
  const raw = await collectText(textChunks);
  return forwardFallback(raw, write);
}

function waitForDrain(stream) {
  return new Promise((resolve, reject) => {
    if (typeof stream.once !== 'function') {
      reject(new Error('response stream does not support drain events'));
      return;
    }
    const cleanup = () => {
      stream.removeListener?.('drain', onDrain);
      stream.removeListener?.('error', onError);
      stream.removeListener?.('close', onClose);
    };
    const onDrain = () => {
      cleanup();
      resolve();
    };
    const onError = (error) => {
      cleanup();
      reject(error);
    };
    const onClose = () => {
      cleanup();
      reject(new Error('response stream closed before drain'));
    };
    stream.once('drain', onDrain);
    stream.once('error', onError);
    stream.once('close', onClose);
  });
}

export function createAwaitableWriter(stream) {
  let tail = Promise.resolve();
  let failure = null;

  function write(value) {
    const operation = tail.then(async () => {
      if (failure) throw failure;
      if (stream.write(value) === false) await waitForDrain(stream);
    });
    tail = operation.catch((error) => {
      if (failure === null) failure = error;
    });
    return operation;
  }

  async function flush() {
    await tail;
    if (failure) throw failure;
  }

  return { write, flush };
}

function isAuthorized(headers, key) {
  for (const [name, value] of Object.entries(headers || {})) {
    if (name.toLowerCase() === 'x-api-key' && value === key) return true;
  }
  return false;
}

function errorMessage(error) {
  return error?.message ?? String(error);
}

export async function handleRelayRequest(event, responseStream, dependencies) {
  let stream = responseStream;
  let writer = null;
  let responsePrepared = false;
  let heartbeat = null;
  let sseStarted = false;
  let terminalQueued = false;

  function prepareResponse(statusCode, contentType) {
    if (responsePrepared) return;
    stream = dependencies.createResponseStream(responseStream, {
      statusCode,
      headers: { 'Content-Type': contentType },
    });
    writer = createAwaitableWriter(stream);
    responsePrepared = true;
  }

  function stopHeartbeat() {
    if (heartbeat === null) return;
    const handle = heartbeat;
    heartbeat = null;
    try {
      dependencies.clearIntervalFn(handle);
    } catch {
      // Terminal gating still prevents writes if timer cancellation fails.
    }
  }

  function writeRelay(value) {
    const type = frameObject(value)?.type;
    const isTerminal = type === 'done' || type === 'error';
    if (terminalQueued) return Promise.resolve();
    if (isTerminal) {
      terminalQueued = true;
      stopHeartbeat();
    }
    return writer.write(value);
  }

  try {
    const key = await dependencies.getApiKey();
    if (!isAuthorized(event.headers || {}, key)) {
      prepareResponse(403, 'text/plain');
      await writer.write('unauthorized');
      return;
    }

    const query = event.queryStringParameters || {};
    const sessionId = query.session_id;
    const prompt = query.prompt;
    if (!sessionId || !prompt) {
      prepareResponse(400, 'text/plain');
      await writer.write('session_id and prompt required');
      return;
    }

    prepareResponse(200, 'text/event-stream');
    sseStarted = true;
    await writeRelay(': connected\n\n');
    heartbeat = dependencies.setIntervalFn(() => {
      writeRelay(': keepalive\n\n').catch(() => {});
    }, 15000);

    const response = await dependencies.invokeAgent({ sessionId, prompt });
    const outcome = await forwardAgentResponse(response, writeRelay);
    if (!outcome.doneSeen && !outcome.errorSeen) {
      await writeRelay(sseEvent({ type: 'done' }));
    }
  } catch (error) {
    try {
      if (sseStarted) {
        await writeRelay(sseEvent({
          type: 'error',
          message: errorMessage(error),
        }));
      } else {
        if (!responsePrepared) prepareResponse(500, 'text/plain');
        await writer.write(`error: ${errorMessage(error)}`);
      }
    } catch {
      // The stream itself failed; cleanup below still owns timer and end.
    }
  } finally {
    stopHeartbeat();
    try {
      if (writer !== null) await writer.flush();
    } catch {
      // A closed stream cannot accept a terminal frame, but must still end.
    }
    stream.end();
  }
}
