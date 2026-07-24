import { Box, SpaceBetween } from '@cloudscape-design/components';
import type { ToolTraceItem, ToolTraceStatus } from '../toolTrace';

interface ToolTracePanelProps {
  items: ToolTraceItem[];
}

const STATUS_LABEL: Record<ToolTraceStatus, string> = {
  queued: 'Queued',
  running: 'Running',
  done: 'Done',
  failed: 'Failed',
};

const STATUS_COLOR: Record<ToolTraceStatus, string> = {
  queued: '#8a8f99',
  running: '#0972d3',
  done: '#037f0c',
  failed: '#d91515',
};

function displayName(item: ToolTraceItem): string {
  return item.label ?? item.name.replace(/_/g, ' ').replace(/^./, (char) => char.toUpperCase());
}

export function ToolTracePanel({ items }: ToolTracePanelProps) {
  if (items.length === 0) {
    return <Box color="text-body-secondary">No tool activity yet.</Box>;
  }

  return (
    <SpaceBetween size="xs">
      {items.map((item) => (
        <div
          key={item.id ?? item.name}
          style={{
            display: 'grid',
            gridTemplateColumns: '10px minmax(0, 1fr) auto',
            alignItems: 'center',
            gap: 10,
            minHeight: 32,
          }}
        >
          <span
            aria-hidden="true"
            style={{
              width: 8,
              height: 8,
              borderRadius: 8,
              background: STATUS_COLOR[item.status],
              display: 'inline-block',
            }}
          />
          <span style={{ minWidth: 0, overflowWrap: 'anywhere' }}>{displayName(item)}</span>
          <Box color="text-body-secondary">{STATUS_LABEL[item.status]}</Box>
        </div>
      ))}
    </SpaceBetween>
  );
}
