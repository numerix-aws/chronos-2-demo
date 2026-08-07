# Tool Trace Panel v2 — Design

**Date:** 2026-08-07
**Scope:** `frontend/` only. No agent-runtime, tools, or infra changes.
**Deploy surface:** SPA rebuild + manual Amplify zip deploy.

## Problem

The Tool trace panel renders a flat, append-only list of tool rows merged from
two sources, and it undersells the demo at exactly the moments it should carry
it:

1. **Dead scaffolding on the hot path.** `frontend/src/toolTrace.ts` still
   regex-parses `::tool-trace{...}` markers out of the streamed prose on every
   chunk (re-scanning the full accumulated text per token), even though the
   structured `{type: "tool"}` SSE events superseded markers and the agent
   system prompt forbids emitting them (`agent/tests/test_system_prompt.py`
   asserts `::tool-trace` is absent).
2. **Poll flood.** Each `check_baseline_mc` / `check_chronos2` poll attempt
   carries its own `tool_use_id` (`agent/runtime/workflow.py` `WorkflowRunner.poll`
   → `call()` → `uuid.uuid4()`), so a ~3-minute Fargate wait emits ~90 events.
   Combined with no grouping, a single session's panel grows into a long
   scroll.
3. **No timing or work detail.** Rows show only a name and a status word. The
   presenter has nothing to point at during the async engine waits.
4. **Failures are swallowed.** `failed` events carry `result.message`
   (`workflow.py` failure yields; `events.py` `_completion_event`), but the
   frontend drops everything except the status.
5. **Cross-turn interleaving.** `App.tsx` `handleSend` seeds each turn's trace
   with `priorTraceEvents`, and `reduceToolTraceEvents` keys by
   `id ?? name`, so repeated calls of the same tool across runs collapse or
   interleave.

**Explicit non-goals** (user-confirmed): the trace does not need to survive
reload / session restore; no pagination or list virtualization; no backend
event enrichment.

## Decision

Frontend-only rework (Approach A of the brainstorm). Rebuild the panel from
the structured events that already stream, grouped **run → stage → call**,
with client-side timing, per-call work summaries, poll collapse, and surfaced
failure messages. Delete the marker-parsing path.

Rejected alternatives:

- **B — backend-enriched events** (exact `duration_ms`, `phase`, `run_started`
  emitted by `WorkflowRunner`): cleaner data model, but requires an agent
  image rebuild + runtime version bump + live-endpoint repoint, and adds
  non-deterministic fields to an event stream the reproducibility verifier
  records. Marginal benefit (exact vs arrival-time durations) for real risk.
  The UI model below does not preclude adding these fields later.
- **C — full timeline redesign** (persisted trace, virtualization, per-call
  input/output inspector): exceeds what the demo needs; persistence was
  explicitly waived.

## 1. Data model — `frontend/src/toolTrace.ts` (rewritten)

**Deleted:** `parseToolTraceEvents`, `reduceToolTraceEvents`, `MARKER_RE`,
`ATTR_RE`, `ToolTraceEvent`/`ToolTraceItem` as currently shaped.

**Retained:** `stripToolTraceMarkers` (and `LINE_MARKER_RE`) — stored session
messages from older deployments may still contain markers in their text; the
chat panel keeps stripping them at render time.

**New types:**

```ts
type TraceCallStatus = 'running' | 'done' | 'failed';
type TraceStageStatus = 'pending' | 'running' | 'done' | 'failed';

interface TraceCall {
  toolUseId: string;
  name: string;
  status: TraceCallStatus;
  startedAt: number;        // Date.now() at arrival of the 'running' event
  endedAt?: number;         // arrival of 'done' | 'failed'
  summary?: string;         // extracted work summary, see below
  errorMessage?: string;    // from result.message on failure
}

interface PollSummary {
  attempts: number;
  lastStatus?: string;      // task_status from the latest check_* result
  startedAt: number;        // first poll arrival
  endedAt?: number;         // poll that reported ready (or failed)
  failed: boolean;
}

interface TraceStage {
  key: StageKey;
  title: string;
  status: TraceStageStatus;
  calls: TraceCall[];
  polling?: PollSummary;
}

interface TraceRun {
  runId: string;            // local timestamp id from handleSend
  promptPreview: string;    // first ~60 chars of the user prompt
  startedAt: number;
  endedAt?: number;
  stages: TraceStage[];     // always the full fixed skeleton, in order
}
```

**Stage mapping** (static, mirrors the demo narration):

| StageKey    | Title               | Tools |
|-------------|---------------------|-------|
| `data`      | Market data         | `load_data` |
| `regime`    | Regime detection    | `plot` with `plot_role === 'regime_ribbon'` |
| `baseline`  | Baseline Monte Carlo| `run_baseline_mc`, `check_baseline_mc` (poll) |
| `chronos`   | Chronos-2           | `run_chronos2`, `check_chronos2` (poll) |
| `blend`     | Blend               | `blend_paths` |
| `pricing`   | Pricing             | `price_book` |
| `plots`     | Plots               | `plot` with `plot_role === 'pfe_overlay'` |
| `other`     | Other               | anything unrecognized (e.g. `lookup_use_case`) |

The `other` stage is only rendered when non-empty; the seven canonical stages
always render (pending skeleton from run start).

**Plot disambiguation:** a `plot` call's stage is decided by `plot_role` in
its result. While a plot is still `running` (no result yet), it is
provisionally assigned: `regime` if the regime stage has no done plot yet,
else `plots`. When the result arrives with status `done`, the call is moved
to the stage its `plot_role` dictates (the reducer re-homes it; provisional
placement is only cosmetic while running). A `failed` plot call has no
`plot_role` available, so it is not re-homed — it stays in the provisional
stage where its running row was placed.

**Poll collapse:** successful `check_baseline_mc` / `check_chronos2` events
never create `TraceCall`s. Each `running` arrival increments
`polling.attempts`; each `done` result updates `polling.lastStatus` from
`task_status` and, when `ready === true`, sets `endedAt`.

A **failed** check event is the exception: it materializes as its own
`TraceCall` row in the stage (name `check_baseline_mc`/`check_chronos2`,
status `failed`, `startedAt` = the poll summary's `startedAt`, `endedAt` =
arrival, `errorMessage` from the event). It also sets `polling.failed` and
stamps `polling.endedAt`. The launch call keeps its own true status — a
successfully launched task whose polling later fails shows `run_*` done and
the check row failed, which matches what actually happened (and matches the
real incident this design grew out of: the chronos2 task launched fine, then
died mid-run).

**Result envelope tolerance:** `done` events from the deterministic workflow
path carry `result = {status: 'ok', result: {...}}` (see `workflow.py`
`call()` yielding `envelope`), while the Strands translator path
(`events.py` `_completion_event`) yields the payload directly. A single
helper unwraps: `payload = result?.result ?? result`, and reads fields only
via type-checked access. Missing fields → no summary, never a render error.

**Work summaries** (best-effort, from known result fields):

| Tool | Summary template | Fields |
|------|------------------|--------|
| `load_data`   | `{n_rows} rows · as-of {as_of_date}` | `n_rows`, `as_of_date` |
| `blend_paths` | `w_stress {w_stress} · {n_paths} paths` | `w_stress` (2 dp), `n_paths` |
| `price_book`  | `{scenario_role} · terminal PFE {terminal.pfe_975}` | `scenario_role`, `terminal.pfe_975` ($ compact, e.g. `$4.90M`) |
| `plot`        | `{plot_role}` | `plot_role` |
| `run_*`       | `Fargate task launched` | presence of `task_arn` |

**Status roll-up per stage:** `failed` if any call failed or `polling.failed`;
`running` if any call running or polling active; `done` if it has ≥1 call and
all are done (and polling, if any, ended ready); else `pending`.

**Failure capture:** on a `failed` event, `errorMessage` is taken from
`result.message` (envelope-tolerant). Stored in full; the UI truncates.

**Reducer:** a pure function
`traceReducer(runs: TraceRun[], action) => TraceRun[]` with actions
`run_started {runId, promptPreview, at}`,
`tool_event {event, at}` (applies to the newest run only),
`run_ended {at, failed}` (stamps `endedAt` on the run; when `failed` is
true, marks still-running calls/stages as failed with a generic "stream ended
before completion" message, and adds a synthetic failed check call for any
stage with active polling so the error is visible in the UI; a clean
completion with `failed: false` only stamps `endedAt`).

## 2. App wiring — `App.tsx`

- State: `const [traceRuns, dispatchTrace] = useReducer(traceReducer, [])`.
  `toolTraceEvents`, `priorTraceEvents`, `structuredTraceEvents`, and every
  `parseToolTraceEvents` call site are removed.
- `handleSend` dispatches `run_started` before streaming. `tool` stream
  events dispatch `tool_event` stamped with `Date.now()`. `chunk` events no
  longer touch trace state (they still run `stripToolTraceMarkers` for the
  visible message text). Stream `error` events append the bracketed error to
  the chat text (unchanged) **and** dispatch `run_ended` so in-flight
  calls/stages show failed. Normal completion dispatches nothing.
- Session restore (`connect`) no longer rebuilds trace events from stored
  messages — the panel starts empty for a restored session (accepted).
- `<ToolTracePanel items={...}>` becomes `<ToolTracePanel runs={traceRuns}>`.

## 3. Panel UI — `components/ToolTracePanel.tsx`

- **Runs:** one Cloudscape `ExpandableSection` per run, newest first. The
  active run renders expanded; starting a new run collapses prior ones
  (controlled `expanded` state seeded by "is newest", user-overridable).
  Header: status dot + prompt preview + total duration (live-ticking while
  running). Visible height is thus bounded to roughly one expanded run.
- **Stages:** inside a run, the seven canonical stage rows always render, in
  pipeline order, from the moment the run starts (pending skeleton the
  presenter can point at). Row = status dot (existing color map, plus grey
  for pending) + title + right-aligned duration + one-line summary of its
  latest done call.
- **Poll heartbeat:** while an engine stage is polling, its summary line
  shows `Fargate task {lastStatus} · attempt {n} · {elapsed}` with a
  1-second interval ticker (single `setInterval` for the panel, active
  while any run is unfinished; cleared when all runs are done, keeping
  call durations live throughout execution).
- **Call detail:** a stage with >1 call (e.g. Pricing's three `price_book`
  calls) gets a small expand toggle revealing per-call rows (name, summary,
  duration, status). Collapsed by default.
- **Failures:** a failed stage renders its `errorMessage` inline in red,
  truncated to ~200 chars, with the full message in a Cloudscape `Popover`.
- Empty state unchanged: "No tool activity yet."

## 4. Testing

Vitest (existing frontend suite conventions):

**Reducer tests** (new `toolTrace.test.ts`, replacing marker-parse tests):
- groups events into run → stage → call per the mapping table
- collapses successful `check_*` events into `PollSummary` (attempts,
  lastStatus, ready)
- a failed `check_*` materializes its own failed call row (with the poll
  summary's start time and the event's error message) while the `run_*`
  launch call keeps its done status
- envelope-wrapped and bare payloads both yield correct summaries
- `price_book` summary formats terminal PFE compactly
- failed event captures `result.message`; failed check marks stage failed
- plot re-homing: regime plot lands in `regime`, pfe_overlay in `plots`
- new `run_started` freezes the prior run (later events don't mutate it)
- `run_ended` (error path) fails in-flight calls; clean end leaves them
- `stripToolTraceMarkers` existing tests retained unchanged

**Component tests** (`ToolTracePanel.test.tsx`):
- pending skeleton renders all seven stages at run start
- poll heartbeat line renders attempts/elapsed
- error message renders for a failed stage
- newest run expanded, prior run collapsed

**E2E:** update `frontend/tests/e2e/happy_path.spec.ts` only where it asserts
on current panel markup (verify at implementation time); the demo-prompt
parity tests in `agent/tests/test_demo_prompts.py` are unaffected (prompts
unchanged).

## 5. Out of scope

- Any change under `agent/`, `tools/`, `infra/`, or to the SSE event schema.
- Persisting trace events (sessions table untouched).
- List virtualization / pagination.
- Removing `stripToolTraceMarkers` (still needed for stored legacy messages).

## Deploy

SPA only: `npm run build` with existing env, manual Amplify zip deploy per
runbook §frontend. No stack deploys, no image rebuilds, no runtime version
bump.
