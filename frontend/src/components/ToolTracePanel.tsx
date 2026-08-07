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
      {expanded && (
        <SpaceBetween size="xs">
          {visibleStages.map((stage) => (
            <StageRow key={stage.key} stage={stage} now={now} />
          ))}
        </SpaceBetween>
      )}
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
