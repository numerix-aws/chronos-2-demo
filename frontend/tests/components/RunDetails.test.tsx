import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { RunDetails } from '../../src/components/RunDetails';

describe('RunDetails', () => {
  it('renders canonical inputs with shortened execution identity', () => {
    render(
      <RunDetails
        runSpec={{
          type: 'run_spec',
          executionId: 'execution-1234567890',
          specHash: 'abcdef1234567890',
          runSpec: {
            profile: 'stage_safe_headline_v1',
            as_of_date: '2022-09-30',
            n_paths: 500,
            baseline_components: 5,
            baseline_seed: 17,
            chronos_seed: 29,
            regime_threshold: 0.7,
            book_id: 'cross_asset_demo_v1',
            conditioning: {
              series_shifts: { EUR_2Y: -0.5, EUR_5Y: -0.25 },
              n_anchor_days: 30,
            },
          },
        }}
      />,
    );

    expect(screen.getByText('stage_safe_headline_v1')).toBeInTheDocument();
    expect(screen.getByText('2022-09-30')).toBeInTheDocument();
    expect(screen.getByText('500')).toBeInTheDocument();
    expect(screen.getByText('Baseline components')).toBeInTheDocument();
    expect(screen.getByText('17')).toBeInTheDocument();
    expect(screen.getByText('29')).toBeInTheDocument();
    expect(screen.getByText('0.7')).toBeInTheDocument();
    expect(screen.getByText('cross_asset_demo_v1')).toBeInTheDocument();
    expect(screen.getByText('EUR_2Y=-0.5, EUR_5Y=-0.25')).toBeInTheDocument();
    expect(screen.getByText('30')).toBeInTheDocument();
    expect(screen.getByText('execution-12...')).toBeInTheDocument();
    expect(screen.getByText('abcdef123456...')).toBeInTheDocument();
  });
});
