import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { DiagnosticsPanel } from '../../src/components/DiagnosticsPanel';

describe('DiagnosticsPanel', () => {
  it('renders all five attribution distributions and both coverage tables', () => {
    render(
      <DiagnosticsPanel
        diagnostics={{
          type: 'diagnostics', executionId: 'run-1', specHash: 'hash-1',
          diagnosticsUri: 's3://diagnostics', diagnosticsSha256: 'diagnostics-1',
          diagnostics: {
            attribution: {
              uniform_parametric: { scenario_role: 'baseline', delta_pfe_975: 0 },
              uniform_chronos: { scenario_role: 'chronos_only', delta_pfe_975: 2 },
              reweighted_parametric: { scenario_role: 'baseline_component', delta_pfe_975: 3 },
              reweighted_chronos: { scenario_role: 'chronos_component', delta_pfe_975: 4 },
              final_blend: { scenario_role: 'augmented', delta_pfe_975: 5 },
            },
            portfolio_coverage: { available: true, results: { final_blend: { coverage: 0.975 } } },
            factor_coverage: { available: true, results: { final_blend: { coverage: 0.95 } } },
          },
        }}
      />,
    );

    expect(screen.getByRole('table', { name: 'Attribution distributions' })).toBeInTheDocument();
    expect(screen.getByText('Uniform Parametric')).toBeInTheDocument();
    expect(screen.getByText('Uniform Chronos')).toBeInTheDocument();
    expect(screen.getByText('Reweighted Parametric')).toBeInTheDocument();
    expect(screen.getByText('Reweighted Chronos')).toBeInTheDocument();
    expect(within(screen.getByRole('table', { name: 'Attribution distributions' })).getByText('Final Blend')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Portfolio Coverage' })).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Factor Coverage' })).toBeInTheDocument();
  });

  it('shows the supplied reason when coverage is unavailable', () => {
    render(
      <DiagnosticsPanel
        diagnostics={{
          type: 'diagnostics', executionId: 'run-1', specHash: 'hash-1',
          diagnosticsUri: 's3://diagnostics', diagnosticsSha256: 'diagnostics-1',
          diagnostics: {
            attribution: {},
            portfolio_coverage: { available: false, reason: 'realized horizon has 3 of 4 required observations' },
            factor_coverage: { available: false, reason: 'realized regimes do not match the forecast horizon' },
          },
        }}
      />,
    );

    expect(screen.getByText(/Portfolio Coverage unavailable: realized horizon has 3 of 4/i)).toBeInTheDocument();
    expect(screen.getByText(/Factor Coverage unavailable: realized regimes do not match/i)).toBeInTheDocument();
  });
});
