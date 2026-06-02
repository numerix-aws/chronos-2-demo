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
