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
