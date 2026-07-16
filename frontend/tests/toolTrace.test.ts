import { describe, expect, it } from 'vitest';
import {
  parseToolTraceEvents,
  reduceToolTraceEvents,
  stripToolTraceMarkers,
} from '../src/toolTrace';

describe('toolTrace', () => {
  it('parses trace directives and strips them from assistant text', () => {
    const text =
      'Starting\n' +
      '::tool-trace{name="load_data" status="running" label="Load data"}\n' +
      'Still readable';

    expect(parseToolTraceEvents(text)).toEqual([
      { name: 'load_data', status: 'running', label: 'Load data' },
    ]);
    expect(stripToolTraceMarkers(text)).toBe('Starting\nStill readable');
  });

  it('keeps tool order while latest status wins', () => {
    const events = parseToolTraceEvents(
      [
        '::tool-trace{name="load_data" status="running"}',
        '::tool-trace{name="run_baseline_mc" status="running" label="Baseline MC"}',
        '::tool-trace{name="load_data" status="done"}',
      ].join('\n'),
    );

    expect(reduceToolTraceEvents(events)).toEqual([
      { name: 'load_data', status: 'done' },
      { name: 'run_baseline_mc', status: 'running', label: 'Baseline MC' },
    ]);
  });
});
