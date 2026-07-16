import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ToolTracePanel } from '../../src/components/ToolTracePanel';

describe('ToolTracePanel', () => {
  it('renders a quiet empty state before any tool markers arrive', () => {
    render(<ToolTracePanel items={[]} />);

    expect(screen.getByText(/No tool activity yet/i)).toBeInTheDocument();
  });

  it('renders tool names and status labels', () => {
    render(
      <ToolTracePanel
        items={[
          { name: 'load_data', status: 'done', label: 'Load market data' },
          { name: 'run_chronos2', status: 'running', label: 'Chronos-2 Fargate' },
        ]}
      />,
    );

    expect(screen.getByText('Load market data')).toBeInTheDocument();
    expect(screen.getByText('Chronos-2 Fargate')).toBeInTheDocument();
    expect(screen.getByText('Done')).toBeInTheDocument();
    expect(screen.getByText('Running')).toBeInTheDocument();
  });
});
