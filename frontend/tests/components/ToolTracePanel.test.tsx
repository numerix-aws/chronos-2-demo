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
