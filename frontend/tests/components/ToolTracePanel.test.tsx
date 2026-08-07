import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
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
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-07T10:00:00Z'));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });
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
    const now = Date.now();
    const run = skeleton({ startedAt: now - 95_000 }); // 1m 35s ago
    run.stages[3] = {
      ...run.stages[3],
      status: 'running',
      calls: [{
        toolUseId: 'l1', name: 'run_chronos2', status: 'done',
        startedAt: now - 95_000, endedAt: now - 94_000, summary: 'Fargate task launched',
      }],
      polling: { attempts: 47, lastStatus: 'RUNNING', startedAt: now - 94_000, failed: false },
    };
    render(<ToolTracePanel runs={[run]} />);
    expect(screen.getByText(/attempt 47/i)).toBeInTheDocument();
    expect(screen.getByText(/RUNNING/)).toBeInTheDocument();
    expect(screen.getByText(/1m 34s/)).toBeInTheDocument(); // elapsed from polling.startedAt
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

  it('renders humanized status in run header', () => {
    const now = Date.now();
    const run = skeleton({ startedAt: now - 5000 });
    run.stages[0].status = 'running';
    run.stages[0].calls = [{
      toolUseId: 'a', name: 'load_data', status: 'running', startedAt: now - 5000,
    }];
    render(<ToolTracePanel runs={[run]} />);
    // Header description should show 'Running' (capitalized) not 'running'
    expect(screen.getByText(/Running · 5s/)).toBeInTheDocument();
  });
});
