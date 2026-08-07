import { describe, expect, it } from 'vitest';
import {
  formatDuration,
  stripToolTraceMarkers,
  traceReducer,
  summaryFor,
  type ToolStreamEvent,
  type TraceRun,
} from '../src/toolTrace';

const start = (runId = 'r1', at = 1000): TraceRun[] =>
  traceReducer([], { type: 'run_started', runId, promptPreview: 'Run the demo', at });

const tool = (
  runs: TraceRun[],
  event: ToolStreamEvent,
  at: number,
): TraceRun[] => traceReducer(runs, { type: 'tool_event', event, at });

const active = (runs: TraceRun[]) => runs[runs.length - 1];
const stage = (runs: TraceRun[], key: string) =>
  active(runs).stages.find((s) => s.key === key)!;

describe('stripToolTraceMarkers', () => {
  it('strips legacy markers from stored message text', () => {
    const text =
      'Starting\n::tool-trace{name="load_data" status="running"}\nStill readable';
    expect(stripToolTraceMarkers(text)).toBe('Starting\nStill readable');
  });
});

describe('traceReducer: runs and stages', () => {
  it('run_started creates a run with the full pending stage skeleton', () => {
    const runs = start();
    expect(runs).toHaveLength(1);
    expect(active(runs).promptPreview).toBe('Run the demo');
    expect(active(runs).stages.map((s) => s.key)).toEqual([
      'data', 'regime', 'baseline', 'chronos', 'blend', 'pricing', 'plots',
    ]);
    expect(active(runs).stages.every((s) => s.status === 'pending')).toBe(true);
  });

  it('routes tool calls to their stage with arrival timing', () => {
    let runs = start();
    runs = tool(runs, { toolUseId: 'a', name: 'load_data', status: 'running' }, 1100);
    expect(stage(runs, 'data').status).toBe('running');
    runs = tool(runs, { toolUseId: 'a', name: 'load_data', status: 'done' }, 1600);
    const call = stage(runs, 'data').calls[0];
    expect(call.status).toBe('done');
    expect(call.endedAt! - call.startedAt).toBe(500);
    expect(stage(runs, 'data').status).toBe('done');
  });

  it('routes unknown tools to a synthetic other stage', () => {
    let runs = start();
    runs = tool(runs, { toolUseId: 'x', name: 'lookup_use_case', status: 'running' }, 1100);
    expect(stage(runs, 'other').calls[0].name).toBe('lookup_use_case');
  });

  it('a new run freezes the previous one', () => {
    let runs = start('r1', 1000);
    runs = tool(runs, { toolUseId: 'a', name: 'load_data', status: 'running' }, 1100);
    runs = traceReducer(runs, {
      type: 'run_started', runId: 'r2', promptPreview: 'What if', at: 2000,
    });
    runs = tool(runs, { toolUseId: 'b', name: 'load_data', status: 'running' }, 2100);
    expect(runs).toHaveLength(2);
    expect(runs[0].stages.find((s) => s.key === 'data')!.calls).toHaveLength(1);
    expect(runs[1].stages.find((s) => s.key === 'data')!.calls).toHaveLength(1);
    expect(runs[1].stages.find((s) => s.key === 'data')!.calls[0].toolUseId).toBe('b');
  });

  it('run_ended on error fails in-flight calls; clean end only stamps endedAt', () => {
    let runs = start();
    runs = tool(runs, { toolUseId: 'a', name: 'blend_paths', status: 'running' }, 1100);
    const errored = traceReducer(runs, { type: 'run_ended', at: 1500, failed: true });
    const failedCall = errored[0].stages.find((s) => s.key === 'blend')!.calls[0];
    expect(failedCall.status).toBe('failed');
    expect(failedCall.errorMessage).toMatch(/stream ended/i);
    expect(errored[0].endedAt).toBe(1500);

    const clean = traceReducer(runs, { type: 'run_ended', at: 1500, failed: false });
    expect(clean[0].stages.find((s) => s.key === 'blend')!.calls[0].status).toBe('running');
    expect(clean[0].endedAt).toBe(1500);
  });

  it('plot re-homes by plot_role: regime first, pfe_overlay to plots', () => {
    let runs = start();
    runs = tool(runs, { toolUseId: 'p1', name: 'plot', status: 'running' }, 1100);
    expect(stage(runs, 'regime').calls).toHaveLength(1);
    runs = tool(runs, {
      toolUseId: 'p1', name: 'plot', status: 'done',
      result: { status: 'ok', result: { plot_role: 'regime_ribbon' } },
    }, 1200);
    expect(stage(runs, 'regime').calls[0].status).toBe('done');

    runs = tool(runs, { toolUseId: 'p2', name: 'plot', status: 'running' }, 1300);
    expect(stage(runs, 'plots').calls).toHaveLength(1);
    runs = tool(runs, {
      toolUseId: 'p2', name: 'plot', status: 'done',
      result: { status: 'ok', result: { plot_role: 'pfe_overlay' } },
    }, 1400);
    expect(stage(runs, 'plots').calls[0].status).toBe('done');
    expect(stage(runs, 'regime').calls).toHaveLength(1);
  });
});

describe('formatDuration', () => {
  it('formats ms, seconds, and minutes', () => {
    expect(formatDuration(850)).toBe('850ms');
    expect(formatDuration(12_000)).toBe('12s');
    expect(formatDuration(94_000)).toBe('1m 34s');
  });
});

describe('traceReducer: poll collapse', () => {
  const launch = (runs: TraceRun[]) =>
    tool(
      tool(runs, { toolUseId: 'l1', name: 'run_chronos2', status: 'running' }, 1100),
      {
        toolUseId: 'l1', name: 'run_chronos2', status: 'done',
        result: { status: 'ok', result: { task_arn: 'arn:aws:ecs:...:task/x' } },
      },
      1200,
    );

  it('successful checks collapse into a PollSummary, never call rows', () => {
    let runs = launch(start());
    for (let i = 0; i < 3; i += 1) {
      runs = tool(runs, { toolUseId: `c${i}`, name: 'check_chronos2', status: 'running' }, 2000 + i * 100);
      runs = tool(runs, {
        toolUseId: `c${i}`, name: 'check_chronos2', status: 'done',
        result: { status: 'ok', result: { task_status: 'RUNNING', ready: false } },
      }, 2050 + i * 100);
    }
    runs = tool(runs, { toolUseId: 'c9', name: 'check_chronos2', status: 'running' }, 3000);
    runs = tool(runs, {
      toolUseId: 'c9', name: 'check_chronos2', status: 'done',
      result: { status: 'ok', result: { task_status: 'STOPPED', ready: true } },
    }, 3100);

    const s = stage(runs, 'chronos');
    expect(s.calls).toHaveLength(1); // only the launch call
    expect(s.polling).toMatchObject({ attempts: 4, lastStatus: 'STOPPED', failed: false });
    expect(s.polling!.endedAt).toBe(3100);
    expect(s.status).toBe('done');
  });

  it('a failed check materializes its own failed row; launch stays done', () => {
    let runs = launch(start());
    runs = tool(runs, { toolUseId: 'c1', name: 'check_chronos2', status: 'running' }, 2000);
    runs = tool(runs, {
      toolUseId: 'c1', name: 'check_chronos2', status: 'failed',
      result: { status: 'error', message: 'chronos2 task arn:... failed: Essential container in task exited (exit code 1)' },
    }, 2500);

    const s = stage(runs, 'chronos');
    expect(s.status).toBe('failed');
    const launchCall = s.calls.find((c) => c.name === 'run_chronos2')!;
    expect(launchCall.status).toBe('done');
    const checkCall = s.calls.find((c) => c.name === 'check_chronos2')!;
    expect(checkCall.status).toBe('failed');
    expect(checkCall.startedAt).toBe(2000); // poll summary start, not event arrival
    expect(checkCall.errorMessage).toMatch(/exit code 1/);
  });
});

describe('summaryFor', () => {
  it('reads envelope-wrapped and bare payloads identically', () => {
    const bare = { n_rows: 1260, as_of_date: '2022-09-30' };
    const wrapped = { status: 'ok', result: bare };
    expect(summaryFor('load_data', bare)).toBe('1,260 rows · as-of 2022-09-30');
    expect(summaryFor('load_data', wrapped)).toBe('1,260 rows · as-of 2022-09-30');
  });

  it('formats blend, pricing, plot, and launch summaries', () => {
    expect(summaryFor('blend_paths', { w_stress: 0.5305, n_paths: 1000 }))
      .toBe('w_stress 0.53 · 1,000 paths');
    expect(summaryFor('price_book', {
      scenario_role: 'baseline', terminal: { pfe_975: 4_900_000 },
    })).toBe('baseline · terminal PFE $4.9M');
    expect(summaryFor('plot', { plot_role: 'pfe_overlay' })).toBe('pfe_overlay');
    expect(summaryFor('run_baseline_mc', { task_arn: 'arn:x' })).toBe('Fargate task launched');
  });

  it('returns undefined on missing fields instead of throwing', () => {
    expect(summaryFor('load_data', {})).toBeUndefined();
    expect(summaryFor('price_book', { scenario_role: 'baseline' })).toBeUndefined();
    expect(summaryFor('load_data', undefined)).toBeUndefined();
  });
});
