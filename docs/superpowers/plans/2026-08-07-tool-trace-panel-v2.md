# Tool Trace Panel v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat, marker-fed Tool trace panel with a run → stage → call model built purely from structured SSE tool events, with client-side timing, poll collapse, work summaries, and surfaced failure messages.

**Architecture:** A pure reducer in `frontend/src/toolTrace.ts` folds `{type:'tool'}` stream events (stamped with arrival time) into `TraceRun[]`; `ToolTracePanel` renders runs as collapsible sections containing a fixed pipeline-stage skeleton. The legacy `::tool-trace{...}` marker parsing is deleted; only `stripToolTraceMarkers` survives (legacy stored messages). No backend changes.

**Tech Stack:** React 18 + TypeScript, Cloudscape components, Vitest + Testing Library (happy-dom), Playwright e2e.

**Spec:** `docs/superpowers/specs/2026-08-07-tool-trace-panel-v2-design.md` — read it before starting any task.

## Global Constraints

- `frontend/` only. Do NOT touch `agent/`, `tools/`, `infra/`, or the SSE event schema.
- `stripToolTraceMarkers` and `LINE_MARKER_RE`/`MARKER_RE` (as needed by it) MUST be retained — stored session messages may still contain markers.
- No persistence of trace state; panel starts empty on session restore.
- Tests: `cd frontend && npx vitest run <file>` for one file, `npm test` for all.
- One commit per task, message as written in the task.
- Existing Cloudscape status colors reused: queued/pending `#8a8f99`, running `#0972d3`, done `#037f0c`, failed `#d91515`.

## File Structure

- `frontend/src/toolTrace.ts` — rewritten: types, stage mapping, `traceReducer`, summary extraction, duration/currency formatters. `stripToolTraceMarkers` kept.
- `frontend/src/components/ToolTracePanel.tsx` — rewritten: renders `TraceRun[]`.
- `frontend/src/App.tsx` — modified: `useReducer` wiring, marker-parse call sites removed.
- `frontend/tests/toolTrace.test.ts` — rewritten (strip tests kept, marker-parse tests deleted, reducer tests added).
- `frontend/tests/components/ToolTracePanel.test.tsx` — rewritten.
- `frontend/tests/App.test.tsx` — two tests updated.
- `frontend/tests/e2e/happy_path.spec.ts` — trace assertions updated to stage titles.

---

### Task 1: Trace data model + reducer core (grouping, timing, skeleton)

**Files:**
- Modify: `frontend/src/toolTrace.ts` (delete `parseToolTraceEvents`, `reduceToolTraceEvents`, `ToolTraceEvent`/`ToolTraceItem`, `ATTR_RE`, `parseAttrs`, `STATUSES`; keep `stripToolTraceMarkers` + its regexes; add everything below)
- Test: `frontend/tests/toolTrace.test.ts` (delete the two marker tests; keep a strip-only test; add reducer tests)

**Interfaces:**
- Consumes: nothing new — self-contained module.
- Produces (used by Tasks 2–4):
  - `type StageKey = 'data' | 'regime' | 'baseline' | 'chronos' | 'blend' | 'pricing' | 'plots' | 'other'`
  - `interface TraceCall { toolUseId: string; name: string; status: 'running' | 'done' | 'failed'; startedAt: number; endedAt?: number; summary?: string; errorMessage?: string }`
  - `interface PollSummary { attempts: number; lastStatus?: string; startedAt: number; endedAt?: number; failed: boolean }`
  - `interface TraceStage { key: StageKey; title: string; status: 'pending' | 'running' | 'done' | 'failed'; calls: TraceCall[]; polling?: PollSummary }`
  - `interface TraceRun { runId: string; promptPreview: string; startedAt: number; endedAt?: number; stages: TraceStage[] }`
  - `interface ToolStreamEvent { toolUseId: string; name: string; status: 'running' | 'done' | 'failed'; result?: unknown }`
  - `type TraceAction = { type: 'run_started'; runId: string; promptPreview: string; at: number } | { type: 'tool_event'; event: ToolStreamEvent; at: number } | { type: 'run_ended'; at: number; failed: boolean }`
  - `function traceReducer(runs: TraceRun[], action: TraceAction): TraceRun[]`
  - `function stripToolTraceMarkers(text: string): string` (unchanged)
  - `function formatDuration(ms: number): string` — `"850ms"` under 1s, `"12s"` under 60s, `"1m 34s"` otherwise.

- [ ] **Step 1: Rewrite the test file with failing reducer tests**

Replace `frontend/tests/toolTrace.test.ts` entirely with:

```ts
import { describe, expect, it } from 'vitest';
import {
  formatDuration,
  stripToolTraceMarkers,
  traceReducer,
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run tests/toolTrace.test.ts`
Expected: FAIL — `traceReducer`/`formatDuration` not exported (compile errors are the expected failure mode here).

- [ ] **Step 3: Rewrite `frontend/src/toolTrace.ts`**

Replace the file contents with:

```ts
// Legacy marker stripping — stored session messages from older deployments
// may still contain ::tool-trace{...} directives in their text.
const MARKER_RE = /::tool-trace\{([^}]*)\}/g;
const LINE_MARKER_RE = /^[ \t]*::tool-trace\{[^}]*\}[ \t]*\n?/gm;

export function stripToolTraceMarkers(text: string): string {
  return text
    .replace(LINE_MARKER_RE, '')
    .replace(MARKER_RE, '')
    .replace(/[ \t]+\n/g, '\n')
    .trimEnd();
}

export type TraceCallStatus = 'running' | 'done' | 'failed';
export type TraceStageStatus = 'pending' | 'running' | 'done' | 'failed';
export type StageKey =
  | 'data' | 'regime' | 'baseline' | 'chronos'
  | 'blend' | 'pricing' | 'plots' | 'other';

export interface TraceCall {
  toolUseId: string;
  name: string;
  status: TraceCallStatus;
  startedAt: number;
  endedAt?: number;
  summary?: string;
  errorMessage?: string;
}

export interface PollSummary {
  attempts: number;
  lastStatus?: string;
  startedAt: number;
  endedAt?: number;
  failed: boolean;
}

export interface TraceStage {
  key: StageKey;
  title: string;
  status: TraceStageStatus;
  calls: TraceCall[];
  polling?: PollSummary;
}

export interface TraceRun {
  runId: string;
  promptPreview: string;
  startedAt: number;
  endedAt?: number;
  stages: TraceStage[];
}

export interface ToolStreamEvent {
  toolUseId: string;
  name: string;
  status: TraceCallStatus;
  result?: unknown;
}

export type TraceAction =
  | { type: 'run_started'; runId: string; promptPreview: string; at: number }
  | { type: 'tool_event'; event: ToolStreamEvent; at: number }
  | { type: 'run_ended'; at: number; failed: boolean };

const STAGE_TITLES: Record<StageKey, string> = {
  data: 'Market data',
  regime: 'Regime detection',
  baseline: 'Baseline Monte Carlo',
  chronos: 'Chronos-2',
  blend: 'Blend',
  pricing: 'Pricing',
  plots: 'Plots',
  other: 'Other',
};

const SKELETON_KEYS: StageKey[] = [
  'data', 'regime', 'baseline', 'chronos', 'blend', 'pricing', 'plots',
];

const TOOL_STAGE: Record<string, StageKey> = {
  load_data: 'data',
  run_baseline_mc: 'baseline',
  check_baseline_mc: 'baseline',
  run_chronos2: 'chronos',
  check_chronos2: 'chronos',
  blend_paths: 'blend',
  price_book: 'pricing',
};

const POLL_TOOLS = new Set(['check_baseline_mc', 'check_chronos2']);

// Tool results arrive either envelope-wrapped ({status:'ok', result:{...}})
// from the deterministic workflow, or as the bare payload from the Strands
// translator path. Read fields through this unwrap only.
export function unwrapResult(result: unknown): Record<string, unknown> {
  if (typeof result !== 'object' || result === null) return {};
  const outer = result as Record<string, unknown>;
  if (outer.status === 'ok' && typeof outer.result === 'object' && outer.result !== null) {
    return outer.result as Record<string, unknown>;
  }
  return outer;
}

function errorMessageFrom(result: unknown): string | undefined {
  if (typeof result !== 'object' || result === null) return undefined;
  const outer = result as Record<string, unknown>;
  if (typeof outer.message === 'string') return outer.message;
  const inner = unwrapResult(result);
  return typeof inner.message === 'string' ? inner.message : undefined;
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const totalSeconds = Math.round(ms / 1000);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  return `${Math.floor(totalSeconds / 60)}m ${totalSeconds % 60}s`;
}

function newRun(runId: string, promptPreview: string, at: number): TraceRun {
  return {
    runId,
    promptPreview,
    startedAt: at,
    stages: SKELETON_KEYS.map((key) => ({
      key,
      title: STAGE_TITLES[key],
      status: 'pending',
      calls: [],
    })),
  };
}

function rollupStatus(s: TraceStage): TraceStageStatus {
  if (s.polling?.failed || s.calls.some((c) => c.status === 'failed')) return 'failed';
  const pollingActive = s.polling !== undefined && s.polling.endedAt === undefined;
  if (pollingActive || s.calls.some((c) => c.status === 'running')) return 'running';
  if (s.calls.length > 0) return 'done';
  return 'pending';
}

function stageKeyFor(event: ToolStreamEvent, run: TraceRun): StageKey {
  if (event.name === 'plot') {
    const role = unwrapResult(event.result).plot_role;
    if (role === 'regime_ribbon') return 'regime';
    if (role === 'pfe_overlay') return 'plots';
    // Running plot with no result yet: regime first, then plots.
    const regime = run.stages.find((s) => s.key === 'regime');
    return regime && regime.calls.length === 0 ? 'regime' : 'plots';
  }
  return TOOL_STAGE[event.name] ?? 'other';
}

function ensureStage(run: TraceRun, key: StageKey): TraceStage {
  let found = run.stages.find((s) => s.key === key);
  if (!found) {
    found = { key, title: STAGE_TITLES[key], status: 'pending', calls: [] };
    run.stages.push(found);
  }
  return found;
}

function applyPoll(run: TraceRun, event: ToolStreamEvent, at: number): void {
  const s = ensureStage(run, TOOL_STAGE[event.name] ?? 'other');
  if (event.status === 'running') {
    if (!s.polling) s.polling = { attempts: 0, startedAt: at, failed: false };
    s.polling.attempts += 1;
  } else if (event.status === 'done') {
    if (!s.polling) s.polling = { attempts: 1, startedAt: at, failed: false };
    const payload = unwrapResult(event.result);
    if (typeof payload.task_status === 'string') s.polling.lastStatus = payload.task_status;
    if (payload.ready === true) s.polling.endedAt = at;
  } else {
    // A failed poll materializes as its own call row; the launch call keeps
    // its true (done) status — the task launched fine, then died mid-run.
    const startedAt = s.polling?.startedAt ?? at;
    if (!s.polling) s.polling = { attempts: 1, startedAt, failed: false };
    s.polling.failed = true;
    s.polling.endedAt = at;
    s.calls.push({
      toolUseId: event.toolUseId,
      name: event.name,
      status: 'failed',
      startedAt,
      endedAt: at,
      errorMessage: errorMessageFrom(event.result) ?? 'task failed',
    });
  }
  s.status = rollupStatus(s);
}

function applyCall(run: TraceRun, event: ToolStreamEvent, at: number): void {
  if (event.status === 'running') {
    const s = ensureStage(run, stageKeyFor(event, run));
    s.calls.push({
      toolUseId: event.toolUseId,
      name: event.name,
      status: 'running',
      startedAt: at,
    });
    s.status = rollupStatus(s);
    return;
  }
  // done | failed: locate the running call anywhere in the run (plot calls
  // may re-home once plot_role arrives).
  let call: TraceCall | undefined;
  let from: TraceStage | undefined;
  for (const s of run.stages) {
    call = s.calls.find((c) => c.toolUseId === event.toolUseId);
    if (call) { from = s; break; }
  }
  if (!call || !from) {
    // Completion without a seen start: create the row where it belongs.
    const s = ensureStage(run, stageKeyFor(event, run));
    call = { toolUseId: event.toolUseId, name: event.name, status: 'running', startedAt: at };
    s.calls.push(call);
    from = s;
  }
  call.status = event.status;
  call.endedAt = at;
  if (event.status === 'failed') {
    call.errorMessage = errorMessageFrom(event.result) ?? 'tool failed';
  } else {
    call.summary = summaryFor(event.name, event.result);
  }
  const target = stageKeyFor(event, run);
  if (from.key !== target) {
    from.calls = from.calls.filter((c) => c.toolUseId !== event.toolUseId);
    ensureStage(run, target).calls.push(call);
  }
  for (const s of run.stages) s.status = rollupStatus(s);
}

export function traceReducer(runs: TraceRun[], action: TraceAction): TraceRun[] {
  if (action.type === 'run_started') {
    return [...runs, newRun(action.runId, action.promptPreview, action.at)];
  }
  if (runs.length === 0) return runs;
  const next = runs.slice(0, -1);
  const run = structuredClone(runs[runs.length - 1]);
  next.push(run);

  if (action.type === 'tool_event') {
    if (POLL_TOOLS.has(action.event.name)) {
      applyPoll(run, action.event, action.at);
    } else {
      applyCall(run, action.event, action.at);
    }
    return next;
  }

  // run_ended
  run.endedAt = action.at;
  if (action.failed) {
    for (const s of run.stages) {
      for (const c of s.calls) {
        if (c.status === 'running') {
          c.status = 'failed';
          c.endedAt = action.at;
          c.errorMessage = c.errorMessage ?? 'stream ended before completion';
        }
      }
      if (s.polling && s.polling.endedAt === undefined) {
        s.polling.failed = true;
        s.polling.endedAt = action.at;
      }
      s.status = rollupStatus(s);
    }
  }
  return next;
}

const compactUsd = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  notation: 'compact',
  maximumFractionDigits: 2,
});

export function summaryFor(name: string, result: unknown): string | undefined {
  const p = unwrapResult(result);
  switch (name) {
    case 'load_data':
      return typeof p.n_rows === 'number' && typeof p.as_of_date === 'string'
        ? `${p.n_rows.toLocaleString('en-US')} rows · as-of ${p.as_of_date}`
        : undefined;
    case 'blend_paths':
      return typeof p.w_stress === 'number' && typeof p.n_paths === 'number'
        ? `w_stress ${p.w_stress.toFixed(2)} · ${p.n_paths.toLocaleString('en-US')} paths`
        : undefined;
    case 'price_book': {
      const terminal = p.terminal as Record<string, unknown> | undefined;
      const pfe = terminal && typeof terminal.pfe_975 === 'number' ? terminal.pfe_975 : undefined;
      return typeof p.scenario_role === 'string' && pfe !== undefined
        ? `${p.scenario_role} · terminal PFE ${compactUsd.format(pfe)}`
        : undefined;
    }
    case 'plot':
      return typeof p.plot_role === 'string' ? p.plot_role : undefined;
    case 'run_baseline_mc':
    case 'run_chronos2':
      return typeof p.task_arn === 'string' ? 'Fargate task launched' : undefined;
    default:
      return undefined;
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run tests/toolTrace.test.ts`
Expected: PASS (all tests in the file).

Note: `frontend/src/App.tsx` and `ToolTracePanel.tsx` still import the deleted
exports, so `npm run build` will fail at this point — that's expected until
Tasks 3–4. Vitest compiles per-file, so this task's test run is unaffected.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/toolTrace.ts frontend/tests/toolTrace.test.ts
git commit -m "feat(frontend): trace reducer with run/stage grouping and timing"
```

---

### Task 2: Poll collapse, failure capture, and summary tests

**Files:**
- Modify: `frontend/src/toolTrace.ts` (only if a test exposes a bug — the Task 1 implementation already contains the poll/summary logic; this task proves it)
- Test: `frontend/tests/toolTrace.test.ts` (append)

**Interfaces:**
- Consumes: `traceReducer`, `summaryFor`, `unwrapResult` from Task 1 (exact signatures above).
- Produces: verified behavior later tasks rely on — polls collapse, failure rows, envelope tolerance.

- [ ] **Step 1: Append the failing/verifying tests**

Append to `frontend/tests/toolTrace.test.ts`:

```ts
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
```

Also add `summaryFor` to the import list at the top of the test file.

- [ ] **Step 2: Run tests**

Run: `cd frontend && npx vitest run tests/toolTrace.test.ts`
Expected: PASS if Task 1's implementation is correct. If any test fails, fix
`frontend/src/toolTrace.ts` minimally until green — the tests, not the Task 1
code, are the contract. (Check the compact-currency expectation first:
`Intl` compact notation renders 4,900,000 as `$4.9M`.)

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/toolTrace.test.ts frontend/src/toolTrace.ts
git commit -m "test(frontend): poll collapse, failure rows, and summary extraction"
```

---

### Task 3: ToolTracePanel rewrite

**Files:**
- Modify: `frontend/src/components/ToolTracePanel.tsx` (full rewrite)
- Test: `frontend/tests/components/ToolTracePanel.test.tsx` (full rewrite)

**Interfaces:**
- Consumes: `TraceRun`, `TraceStage`, `TraceCall`, `formatDuration` from `../toolTrace` (Task 1 signatures).
- Produces: `export function ToolTracePanel({ runs }: { runs: TraceRun[] })` — consumed by Task 4.

- [ ] **Step 1: Rewrite the component test with failing tests**

Replace `frontend/tests/components/ToolTracePanel.test.tsx` with:

```tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ToolTracePanel } from '../../src/components/ToolTracePanel';
import type { TraceRun } from '../../src/toolTrace';

const skeleton = (over: Partial<TraceRun> = {}): TraceRun => ({
  runId: 'r1',
  promptPreview: 'Run the stage-safe headline demo',
  startedAt: 1000,
  stages: [
    { key: 'data', title: 'Market data', status: 'pending', calls: [] },
    { key: 'regime', title: 'Regime detection', status: 'pending', calls: [] },
    { key: 'baseline', title: 'Baseline Monte Carlo', status: 'pending', calls: [] },
    { key: 'chronos', title: 'Chronos-2', status: 'pending', calls: [] },
    { key: 'blend', title: 'Blend', status: 'pending', calls: [] },
    { key: 'pricing', title: 'Pricing', status: 'pending', calls: [] },
    { key: 'plots', title: 'Plots', status: 'pending', calls: [] },
  ],
  ...over,
});

describe('ToolTracePanel', () => {
  it('renders a quiet empty state with no runs', () => {
    render(<ToolTracePanel runs={[]} />);
    expect(screen.getByText(/No tool activity yet/i)).toBeInTheDocument();
  });

  it('renders the full stage skeleton from run start', () => {
    render(<ToolTracePanel runs={[skeleton()]} />);
    for (const title of [
      'Market data', 'Regime detection', 'Baseline Monte Carlo',
      'Chronos-2', 'Blend', 'Pricing', 'Plots',
    ]) {
      expect(screen.getByText(title)).toBeInTheDocument();
    }
  });

  it('shows a poll heartbeat line while an engine stage is polling', () => {
    const run = skeleton();
    run.stages[3] = {
      ...run.stages[3],
      status: 'running',
      calls: [{
        toolUseId: 'l1', name: 'run_chronos2', status: 'done',
        startedAt: 1000, endedAt: 1200, summary: 'Fargate task launched',
      }],
      polling: { attempts: 47, lastStatus: 'RUNNING', startedAt: 1200, failed: false },
    };
    render(<ToolTracePanel runs={[run]} />);
    expect(screen.getByText(/attempt 47/i)).toBeInTheDocument();
    expect(screen.getByText(/RUNNING/)).toBeInTheDocument();
  });

  it('renders failure messages for failed stages', () => {
    const run = skeleton();
    run.stages[3] = {
      ...run.stages[3],
      status: 'failed',
      calls: [{
        toolUseId: 'c1', name: 'check_chronos2', status: 'failed',
        startedAt: 1000, endedAt: 2000,
        errorMessage: 'Essential container in task exited (exit code 1)',
      }],
    };
    render(<ToolTracePanel runs={[run]} />);
    expect(screen.getByText(/exit code 1/)).toBeInTheDocument();
  });

  it('expands only the newest run', () => {
    const old = skeleton({ runId: 'r1', promptPreview: 'first run', endedAt: 5000 });
    const current = skeleton({ runId: 'r2', promptPreview: 'second run', startedAt: 6000 });
    render(<ToolTracePanel runs={[old, current]} />);
    // Both headers visible; only the newest run's stages render (old collapsed).
    expect(screen.getByText(/first run/)).toBeInTheDocument();
    expect(screen.getByText(/second run/)).toBeInTheDocument();
    expect(screen.getAllByText('Market data')).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run tests/components/ToolTracePanel.test.tsx`
Expected: FAIL — component still has the old `items` prop shape.

- [ ] **Step 3: Rewrite the component**

Replace `frontend/src/components/ToolTracePanel.tsx` with:

```tsx
import { useEffect, useReducer, useState } from 'react';
import { Box, ExpandableSection, Popover, SpaceBetween } from '@cloudscape-design/components';
import {
  formatDuration,
  type TraceCall,
  type TraceRun,
  type TraceStage,
  type TraceStageStatus,
} from '../toolTrace';

const STATUS_COLOR: Record<TraceStageStatus, string> = {
  pending: '#8a8f99',
  running: '#0972d3',
  done: '#037f0c',
  failed: '#d91515',
};

function Dot({ status }: { status: TraceStageStatus }) {
  return (
    <span
      aria-hidden="true"
      style={{
        width: 8,
        height: 8,
        borderRadius: 8,
        background: STATUS_COLOR[status],
        display: 'inline-block',
        flexShrink: 0,
      }}
    />
  );
}

function ErrorText({ message }: { message: string }) {
  const truncated = message.length > 200 ? `${message.slice(0, 200)}…` : message;
  const body = (
    <span style={{ color: STATUS_COLOR.failed, overflowWrap: 'anywhere' }}>{truncated}</span>
  );
  if (truncated === message) return body;
  return <Popover content={message} dismissButton={false}>{body}</Popover>;
}

function durationOf(start: number, end: number | undefined, now: number): string {
  return formatDuration((end ?? now) - start);
}

function CallRow({ call, now }: { call: TraceCall; now: number }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, paddingLeft: 18 }}>
      <Dot status={call.status} />
      <span style={{ fontFamily: 'monospace', fontSize: '0.85em' }}>{call.name}</span>
      {call.summary && <Box color="text-body-secondary" fontSize="body-s">{call.summary}</Box>}
      {call.errorMessage && <ErrorText message={call.errorMessage} />}
      <span style={{ marginLeft: 'auto', whiteSpace: 'nowrap' }}>
        <Box color="text-body-secondary" fontSize="body-s">
          {durationOf(call.startedAt, call.endedAt, now)}
        </Box>
      </span>
    </div>
  );
}

function stageSummary(stage: TraceStage, now: number): string | undefined {
  if (stage.polling && !stage.polling.endedAt && !stage.polling.failed) {
    const elapsed = formatDuration(now - stage.polling.startedAt);
    const status = stage.polling.lastStatus ?? 'PENDING';
    return `Fargate task ${status} · attempt ${stage.polling.attempts} · ${elapsed}`;
  }
  const lastDone = [...stage.calls].reverse().find((c) => c.status === 'done' && c.summary);
  return lastDone?.summary;
}

function stageDuration(stage: TraceStage, now: number): string | undefined {
  const starts = stage.calls.map((c) => c.startedAt);
  if (stage.polling) starts.push(stage.polling.startedAt);
  if (starts.length === 0) return undefined;
  const ends = stage.calls.map((c) => c.endedAt ?? now);
  if (stage.polling) ends.push(stage.polling.endedAt ?? now);
  return formatDuration(Math.max(...ends) - Math.min(...starts));
}

function StageRow({ stage, now }: { stage: TraceStage; now: number }) {
  const [showCalls, setShowCalls] = useState(false);
  const summary = stageSummary(stage, now);
  const duration = stageDuration(stage, now);
  const failedCall = stage.calls.find((c) => c.errorMessage);
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, minHeight: 28 }}>
        <Dot status={stage.status} />
        <span>{stage.title}</span>
        {summary && <Box color="text-body-secondary" fontSize="body-s">{summary}</Box>}
        {stage.calls.length > 1 && (
          <button
            type="button"
            onClick={() => setShowCalls((v) => !v)}
            style={{ border: 'none', background: 'none', cursor: 'pointer', color: '#0972d3', padding: 0 }}
          >
            {showCalls ? 'hide calls' : `${stage.calls.length} calls`}
          </button>
        )}
        {duration && (
          <span style={{ marginLeft: 'auto', whiteSpace: 'nowrap' }}>
            <Box color="text-body-secondary" fontSize="body-s">{duration}</Box>
          </span>
        )}
      </div>
      {stage.status === 'failed' && failedCall?.errorMessage && !showCalls && (
        <div style={{ paddingLeft: 18 }}>
          <ErrorText message={failedCall.errorMessage} />
        </div>
      )}
      {showCalls && (
        <SpaceBetween size="xxs">
          {stage.calls.map((call) => (
            <CallRow key={call.toolUseId} call={call} now={now} />
          ))}
        </SpaceBetween>
      )}
    </div>
  );
}

function runStatus(run: TraceRun): TraceStageStatus {
  if (run.stages.some((s) => s.status === 'failed')) return 'failed';
  if (run.stages.some((s) => s.status === 'running')) return 'running';
  if (run.stages.some((s) => s.status === 'done')) return run.endedAt ? 'done' : 'running';
  return 'pending';
}

function RunSection({ run, isNewest, now }: { run: TraceRun; isNewest: boolean; now: number }) {
  const [expanded, setExpanded] = useState(isNewest);
  useEffect(() => setExpanded(isNewest), [isNewest]);
  const visibleStages = run.stages.filter((s) => s.key !== 'other' || s.calls.length > 0);
  return (
    <ExpandableSection
      variant="footer"
      expanded={expanded}
      onChange={({ detail }) => setExpanded(detail.expanded)}
      headerText={run.promptPreview}
      headerDescription={`${runStatus(run)} · ${durationOf(run.startedAt, run.endedAt, now)}`}
    >
      <SpaceBetween size="xs">
        {visibleStages.map((stage) => (
          <StageRow key={stage.key} stage={stage} now={now} />
        ))}
      </SpaceBetween>
    </ExpandableSection>
  );
}

export function ToolTracePanel({ runs }: { runs: TraceRun[] }) {
  const anyActive = runs.some((run) => run.endedAt === undefined);
  const [, tick] = useReducer((x: number) => x + 1, 0);
  useEffect(() => {
    if (!anyActive) return undefined;
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [anyActive]);
  const now = Date.now();

  if (runs.length === 0) {
    return <Box color="text-body-secondary">No tool activity yet.</Box>;
  }
  const ordered = [...runs].reverse();
  return (
    <SpaceBetween size="s">
      {ordered.map((run, index) => (
        <RunSection key={run.runId} run={run} isNewest={index === 0} now={now} />
      ))}
    </SpaceBetween>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run tests/components/ToolTracePanel.test.tsx`
Expected: PASS. If Cloudscape's `ExpandableSection` renders collapsed content
into the DOM in happy-dom (making the "expands only the newest run" test see
two "Market data" nodes), gate the children instead:
`{expanded && <SpaceBetween …>}` inside `RunSection`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ToolTracePanel.tsx frontend/tests/components/ToolTracePanel.test.tsx
git commit -m "feat(frontend): run/stage tool trace panel with heartbeat and errors"
```

---

### Task 4: App wiring + App test updates

**Files:**
- Modify: `frontend/src/App.tsx`
- Test: `frontend/tests/App.test.tsx`

**Interfaces:**
- Consumes: `traceReducer`, `TraceAction`, `TraceRun`, `stripToolTraceMarkers` (Task 1); `ToolTracePanel({ runs })` (Task 3).
- Produces: the final integrated app — no downstream consumers.

- [ ] **Step 1: Update the two App tests to the new behavior (failing first)**

In `frontend/tests/App.test.tsx`:

(a) Replace the test `renders streamed tool trace markers outside the chat transcript` with:

```tsx
  it('strips legacy trace markers from chat text without creating trace rows', async () => {
    async function* traceStream() {
      yield {
        type: 'chunk' as const,
        text: 'Starting\n::tool-trace{name="load_data" status="running" label="Load data"}\n',
      };
      yield { type: 'chunk' as const, text: 'Done.' };
    }
    streamAgentMock.mockReturnValue(traceStream());

    render(<App />);
    await userEvent.type(screen.getByLabelText(/message/i), 'run demo');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));

    const chat = screen.getByRole('region', { name: /^chat$/i });
    await screen.findByText(/Done\./);
    expect(chat).not.toHaveTextContent('::tool-trace');

    const trace = screen.getByRole('region', { name: /tool trace/i });
    // Markers no longer feed the trace; the run skeleton renders instead.
    expect(trace).toHaveTextContent('Market data');
    expect(trace).not.toHaveTextContent('Load data');
  });
```

(b) In the test `renders structured exposure by role regardless of arrival order and keeps text, trace, and HTTPS plots`, replace the two trace assertions:

```tsx
    const trace = await screen.findByRole('region', { name: /tool trace/i });
    expect(trace).toHaveTextContent('Market data');
    expect(trace).toHaveTextContent('Pricing');
    expect(trace).toHaveTextContent('not a completed result');
```

(the `price_book` failed event's `result.message` must now surface in the panel).

(c) If any other test references `parseToolTraceEvents` or passes `items=` to the panel, update it the same way (search the file for `tool-trace` and `ToolTracePanel`).

- [ ] **Step 2: Run App tests to verify the updated ones fail**

Run: `cd frontend && npx vitest run tests/App.test.tsx`
Expected: the two updated tests FAIL (App still uses the old wiring); others PASS.

- [ ] **Step 3: Rewire App.tsx**

In `frontend/src/App.tsx`:

1. Imports — replace the toolTrace import block with:

```tsx
import {
  stripToolTraceMarkers,
  traceReducer,
  type TraceRun,
} from './toolTrace';
```

Remove `ToolTracePanel`'s old import only if the path changes (it doesn't — keep it).
Add `useReducer` to the React import.

2. State — replace
`const [toolTraceEvents, setToolTraceEvents] = useState<ToolTraceEvent[]>([]);`
with
`const [traceRuns, dispatchTrace] = useReducer(traceReducer, [] as TraceRun[]);`

3. Session-restore effect — delete the line
`setToolTraceEvents(r.messages.flatMap((m) => parseToolTraceEvents(m.content)));`
(keep the `stripToolTraceMarkers` mapping of message content).

4. `handleSend` — delete `const priorTraceEvents = toolTraceEvents;` and
`const structuredTraceEvents: ToolTraceEvent[] = [];`. After `setStreaming(true);` add:

```tsx
    dispatchTrace({
      type: 'run_started',
      runId: `run-${Date.now()}`,
      promptPreview: text.length > 60 ? `${text.slice(0, 60)}…` : text,
      at: Date.now(),
    });
```

5. In the stream loop:
   - `chunk` branch: remove the `setToolTraceEvents([...])` call entirely (keep `rawAcc` accumulation and `stripToolTraceMarkers` for the visible text).
   - `tool` branch: replace the `structuredTraceEvents.push(...)` + `setToolTraceEvents(...)` block with:

```tsx
        dispatchTrace({
          type: 'tool_event',
          at: Date.now(),
          event: {
            toolUseId: ev.toolUseId,
            name: ev.name,
            status: ev.status,
            ...(ev.result !== undefined ? { result: ev.result } : {}),
          },
        });
```

   (keep the existing `plot`/`done` artifact handling below it unchanged).
   - `error` branch: after the existing `setMessages` update add
     `dispatchTrace({ type: 'run_ended', at: Date.now(), failed: true });`
6. After the `for await` loop completes normally (inside the `try`, after the loop), add
   `dispatchTrace({ type: 'run_ended', at: Date.now(), failed: false });`
   In the `catch` block (stream threw), add
   `dispatchTrace({ type: 'run_ended', at: Date.now(), failed: true });`
7. Render — replace
`<ToolTracePanel items={reduceToolTraceEvents(toolTraceEvents)} />`
with
`<ToolTracePanel runs={traceRuns} />`
and remove `reduceToolTraceEvents` from imports.

- [ ] **Step 4: Run the full frontend suite and typecheck**

Run: `cd frontend && npm test && npm run build`
Expected: all vitest suites PASS; `tsc` build clean (this also proves no
lingering imports of the deleted exports).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/tests/App.test.tsx
git commit -m "feat(frontend): wire trace reducer into App, drop marker parsing"
```

---

### Task 5: E2E assertion update + full verification

**Files:**
- Modify: `frontend/tests/e2e/happy_path.spec.ts:220-222`
- Test: full repo suites (the e2e run itself needs the live stack and is NOT required to complete this task — see Step 2)

**Interfaces:**
- Consumes: stage titles from Task 1 (`Market data`, `Pricing`).
- Produces: nothing downstream.

- [ ] **Step 1: Update the e2e trace assertions**

In `frontend/tests/e2e/happy_path.spec.ts`, replace:

```ts
    const toolTrace = page.getByRole('region', { name: /tool trace/i });
    await expect(toolTrace).toContainText(/Load data/i, { timeout: 6 * 60 * 1000 });
    await expect(toolTrace).toContainText(/Price book/i, { timeout: 6 * 60 * 1000 });
```

with:

```ts
    const toolTrace = page.getByRole('region', { name: /tool trace/i });
    await expect(toolTrace).toContainText(/Market data/i, { timeout: 6 * 60 * 1000 });
    await expect(toolTrace).toContainText(/Pricing/i, { timeout: 6 * 60 * 1000 });
```

Search the rest of the spec for other trace-panel text assertions (`Load data`, `Price book`, `Blend paths`, etc.) and update them to stage titles the same way.

- [ ] **Step 2: Full verification**

Run: `cd frontend && npm test && npm run build`
Expected: PASS / clean build.

Run: `source .venv/bin/activate && pytest agent/tests -q`
Expected: PASS (prompt-parity tests unaffected — prompts unchanged; this is a guard).

The Playwright e2e (`npm run e2e`) requires the deployed stack and `.env`
credentials; run it only if the environment is configured (`RUN_E2E=1`), and
do not block the task on it.

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/e2e/happy_path.spec.ts
git commit -m "test(e2e): assert on trace stage titles"
```
