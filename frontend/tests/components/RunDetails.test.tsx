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
          runSpec: { profile: 'stage_safe_headline_v1', as_of_date: '2022-09-30', n_paths: 500 },
        }}
      />,
    );

    expect(screen.getByText('stage_safe_headline_v1')).toBeInTheDocument();
    expect(screen.getByText('2022-09-30')).toBeInTheDocument();
    expect(screen.getByText('500')).toBeInTheDocument();
    expect(screen.getByText('execution-12...')).toBeInTheDocument();
    expect(screen.getByText('abcdef123456...')).toBeInTheDocument();
  });
});
