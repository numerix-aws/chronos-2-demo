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

export async function forwardAgentResponse(response, write) {
  const contentType = String(response.contentType || '').toLowerCase();
  const decoder = new TextDecoder();
  let doneFrame = null;
  let doneSeen = false;
  let errorSeen = false;

  function forwardFrame(frame) {
    const event = frameObject(frame);
    if (event?.type === 'done') {
      doneSeen = true;
      if (doneFrame === null) doneFrame = frame;
      return;
    }
    if (event?.type === 'error') errorSeen = true;
    write(frame);
  }

  if (contentType.includes('text/event-stream')) {
    let buffer = '';
    for await (const chunk of response.response) {
      buffer += decoder.decode(chunk, { stream: true });
      let parsed;
      while ((parsed = nextFrame(buffer)) !== null) {
        forwardFrame(parsed[0]);
        buffer = parsed[1];
      }
    }
    buffer += decoder.decode();
    let parsed;
    while ((parsed = nextFrame(buffer)) !== null) {
      forwardFrame(parsed[0]);
      buffer = parsed[1];
    }
    if (buffer) forwardFrame(`${buffer}\n\n`);
    if (doneFrame !== null && !errorSeen) write(doneFrame);
    return { doneSeen, errorSeen };
  }

  let raw = '';
  for await (const chunk of response.response) {
    raw += decoder.decode(chunk, { stream: true });
  }
  raw += decoder.decode();
  if (!raw) return { doneSeen, errorSeen };

  let decoded;
  try {
    decoded = JSON.parse(raw);
  } catch {
    decoded = raw;
  }
  const event = typeof decoded === 'string'
    ? { type: 'text', text: decoded }
    : decoded;
  forwardFrame(sseEvent(event));
  if (doneFrame !== null && !errorSeen) write(doneFrame);
  return { doneSeen, errorSeen };
}
