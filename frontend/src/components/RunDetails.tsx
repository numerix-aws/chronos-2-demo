import { Box } from '@cloudscape-design/components';
import type { RunSpecEvent } from '../api/stream';

interface RunDetailsProps {
  runSpec: RunSpecEvent | null;
}

const INPUTS = [
  ['profile', 'Profile'],
  ['as_of_date', 'As of date'],
  ['lookback_days', 'Lookback days'],
  ['horizon', 'Horizon'],
  ['n_paths', 'Paths'],
  ['baseline_components', 'Baseline components'],
  ['baseline_seed', 'Baseline seed'],
  ['chronos_seed', 'Chronos seed'],
  ['w_stress', 'Stress weight'],
  ['regime_threshold', 'Regime threshold'],
  ['book_id', 'Book ID'],
] as const;

function shortHash(value: string): string {
  return value.length > 12 ? `${value.slice(0, 12)}...` : value;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function RunDetails({ runSpec }: RunDetailsProps) {
  if (!runSpec) return <Box color="text-body-secondary">No run specification yet.</Box>;
  const conditioning = asRecord(runSpec.runSpec.conditioning);
  const shifts = asRecord(conditioning?.series_shifts);

  return (
    <dl style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '8px 16px', margin: 0 }}>
      {INPUTS.filter(([key]) => key in runSpec.runSpec).map(([key, label]) => (
        <div key={key}>
          <dt>{label}</dt>
          <dd style={{ margin: 0 }}>{String(runSpec.runSpec[key])}</dd>
        </div>
      ))}
      {shifts && (
        <div>
          <dt>Conditioning shifts</dt>
          <dd style={{ margin: 0 }}>
            {Object.entries(shifts).map(([name, value]) => `${name}=${String(value)}`).join(', ')}
          </dd>
        </div>
      )}
      {conditioning && 'n_anchor_days' in conditioning && (
        <div>
          <dt>Conditioning anchor days</dt>
          <dd style={{ margin: 0 }}>{String(conditioning.n_anchor_days)}</dd>
        </div>
      )}
      <div><dt>Execution</dt><dd style={{ margin: 0 }}>{shortHash(runSpec.executionId)}</dd></div>
      <div><dt>Spec hash</dt><dd style={{ margin: 0 }}>{shortHash(runSpec.specHash)}</dd></div>
    </dl>
  );
}
