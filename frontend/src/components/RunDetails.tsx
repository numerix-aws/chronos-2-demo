import { Box } from '@cloudscape-design/components';
import type { RunSpecEvent } from '../api/stream';

interface RunDetailsProps {
  runSpec: RunSpecEvent | null;
}

const INPUTS = ['profile', 'as_of_date', 'lookback_days', 'horizon', 'n_paths', 'w_stress'];

function shortHash(value: string): string {
  return value.length > 12 ? `${value.slice(0, 12)}...` : value;
}

export function RunDetails({ runSpec }: RunDetailsProps) {
  if (!runSpec) return <Box color="text-body-secondary">No run specification yet.</Box>;

  return (
    <dl style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '8px 16px', margin: 0 }}>
      {INPUTS.filter((key) => key in runSpec.runSpec).map((key) => (
        <div key={key}>
          <dt>{key.replace(/_/g, ' ')}</dt>
          <dd style={{ margin: 0 }}>{String(runSpec.runSpec[key])}</dd>
        </div>
      ))}
      <div><dt>Execution</dt><dd style={{ margin: 0 }}>{shortHash(runSpec.executionId)}</dd></div>
      <div><dt>Spec hash</dt><dd style={{ margin: 0 }}>{shortHash(runSpec.specHash)}</dd></div>
    </dl>
  );
}
