import { Box } from '@cloudscape-design/components';
import type { DiagnosticsEvent } from '../api/stream';

interface DiagnosticsPanelProps {
  diagnostics: DiagnosticsEvent | null;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function label(value: string): string {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

function coverage(name: string, value: unknown) {
  const item = asRecord(value);
  if (!item) return null;
  if (item.available === false) {
    return <Box key={name}>{label(name)} unavailable: {String(item.reason ?? 'No coverage data.')}</Box>;
  }
  const results = asRecord(item.results);
  if (!results) return <Box key={name}>{label(name)} available.</Box>;
  return (
    <div key={name}>
      <strong>{label(name)}</strong>
      <table aria-label={label(name)} style={{ width: '100%', borderCollapse: 'collapse' }}>
        <tbody>
          {Object.entries(results).map(([distribution, result]) => {
            const row = asRecord(result);
            return <tr key={distribution}><td>{label(distribution)}</td><td>{String(row?.coverage ?? 'n/a')}</td></tr>;
          })}
        </tbody>
      </table>
    </div>
  );
}

export function DiagnosticsPanel({ diagnostics }: DiagnosticsPanelProps) {
  if (!diagnostics) return <Box color="text-body-secondary">No diagnostics yet.</Box>;
  const attribution = asRecord(diagnostics.diagnostics.attribution) ?? {};
  return (
    <div>
      <table aria-label="Attribution distributions" style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr><th>Distribution</th><th>Scenario role</th><th>PFE delta</th></tr></thead>
        <tbody>
          {Object.entries(attribution).map(([name, value]) => {
            const item = asRecord(value);
            return <tr key={name}><td>{label(name)}</td><td>{String(item?.scenario_role ?? 'n/a')}</td><td>{String(item?.delta_pfe_975 ?? 'n/a')}</td></tr>;
          })}
        </tbody>
      </table>
      {coverage('portfolio_coverage', diagnostics.diagnostics.portfolio_coverage)}
      {coverage('factor_coverage', diagnostics.diagnostics.factor_coverage)}
    </div>
  );
}
