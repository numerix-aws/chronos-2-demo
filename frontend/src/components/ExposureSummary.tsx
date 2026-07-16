import { Box } from '@cloudscape-design/components';
import type { Message } from '../api/client';

interface ExposureRow {
  label: string;
  date?: string;
  ee: number | null;
  pfe975: number | null;
  es975: number | null;
}

interface ExposureSummaryProps {
  messages: Message[];
}

const JSON_BLOCK_RE = /```[^\n\r]*(?:\r?\n)([\s\S]*?)```/gi;

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function parseNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value !== 'string') return null;

  const trimmed = value.trim();
  const multiplier = /m$/i.test(trimmed) ? 1_000_000 : /k$/i.test(trimmed) ? 1_000 : 1;
  const numeric = Number(trimmed.replace(/[$,\s]/g, '').replace(/[mk]$/i, ''));
  return Number.isFinite(numeric) ? numeric * multiplier : null;
}

function terminalNumber(value: unknown): number | null {
  if (Array.isArray(value)) {
    for (let i = value.length - 1; i >= 0; i -= 1) {
      const parsed = parseNumber(value[i]);
      if (parsed !== null) return parsed;
    }
    return null;
  }
  return parseNumber(value);
}

function formatLabel(key: string): string {
  return key
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())
    .replace('Pfe', 'PFE')
    .replace('Ee', 'EE')
    .replace('Es', 'ES');
}

function rowFromRecord(label: string, value: unknown): ExposureRow | null {
  const record = asRecord(value);
  if (!record) return null;

  const ee = terminalNumber(record.ee);
  const pfe975 = terminalNumber(record.pfe_975 ?? record.pfe975 ?? record.pfe);
  const es975 = terminalNumber(record.es_975 ?? record.es975 ?? record.es);
  if (ee === null && pfe975 === null && es975 === null) return null;

  const dates = record.dates;
  const date =
    typeof record.date === 'string'
      ? record.date
      : Array.isArray(dates) && typeof dates[dates.length - 1] === 'string'
        ? dates[dates.length - 1]
        : undefined;

  return { label, date, ee, pfe975, es975 };
}

function rowsFromObject(value: unknown): ExposureRow[] {
  const root = asRecord(value);
  const result = asRecord(root?.result) ?? root;
  const summary = asRecord(result?.exposure_summary ?? result?.exposureSummary) ?? result;
  if (!summary) return [];

  const preferredRows = ['baseline', 'augmented']
    .map((key) => rowFromRecord(formatLabel(key), summary[key]))
    .filter((row): row is ExposureRow => row !== null);
  if (preferredRows.length > 0) return preferredRows;

  const namedRows = Object.entries(summary)
    .map(([key, item]) => rowFromRecord(formatLabel(key), item))
    .filter((row): row is ExposureRow => row !== null);
  if (namedRows.length > 0) return namedRows;

  const latestRow = rowFromRecord('Latest run', summary);
  return latestRow ? [latestRow] : [];
}

function contentVariants(content: string): string[] {
  const variants = [content];
  const trimmed = content.trim();
  if (trimmed.startsWith('"') && trimmed.endsWith('"')) {
    try {
      const decoded = JSON.parse(trimmed);
      if (typeof decoded === 'string') variants.push(decoded);
    } catch {
      // The assistant stream may be plain markdown or a JSON string payload.
    }
  }
  return variants;
}

function parseJsonCandidates(content: string): unknown[] {
  const candidates: string[] = [];
  for (const variant of contentVariants(content)) {
    for (const match of variant.matchAll(JSON_BLOCK_RE)) {
      candidates.push(match[1]);
    }

    const trimmed = variant.trim();
    if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
      candidates.push(trimmed);
    }
  }

  return candidates
    .map((candidate) => {
      try {
        return JSON.parse(candidate);
      } catch {
        return null;
      }
    })
    .filter((value): value is unknown => value !== null);
}

export function extractExposureRows(messages: Message[]): ExposureRow[] {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const parsed = parseJsonCandidates(messages[i].content);
    for (let j = parsed.length - 1; j >= 0; j -= 1) {
      const rows = rowsFromObject(parsed[j]);
      if (rows.length > 0) return rows;
    }
  }
  return [];
}

function formatUsd(value: number | null): string {
  if (value === null) return 'n/a';
  const sign = value < 0 ? '-' : '';
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(1)}K`;
  return `${sign}$${abs.toFixed(0)}`;
}

export function ExposureSummary({ messages }: ExposureSummaryProps) {
  const rows = extractExposureRows(messages);

  if (rows.length === 0) {
    return <Box color="text-body-secondary">No exposure summary yet.</Box>;
  }

  return (
    <div
      style={{
        overflowX: 'auto',
        border: '1px solid #d5dbdb',
        borderRadius: 4,
        background: '#ffffff',
      }}
    >
      <table
        aria-label="Exposure metrics"
        style={{
          width: '100%',
          minWidth: 620,
          borderCollapse: 'collapse',
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        <thead>
          <tr>
            {['Run', 'Date', 'EE', 'PFE 97.5%', 'ES 97.5%'].map((heading) => (
              <th
                key={heading}
                scope="col"
                style={{
                  padding: '10px 12px',
                  textAlign: heading === 'Run' || heading === 'Date' ? 'left' : 'right',
                  borderBottom: '1px solid #d5dbdb',
                  background: '#f2f3f3',
                  color: '#414d5c',
                  fontWeight: 700,
                }}
              >
                {heading}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.label}-${row.date ?? 'no-date'}`}>
              <td style={{ padding: '10px 12px', borderBottom: '1px solid #eaeded' }}>
                {row.label}
              </td>
              <td style={{ padding: '10px 12px', borderBottom: '1px solid #eaeded' }}>
                {row.date ?? 'n/a'}
              </td>
              <td
                style={{
                  padding: '10px 12px',
                  borderBottom: '1px solid #eaeded',
                  textAlign: 'right',
                }}
              >
                {formatUsd(row.ee)}
              </td>
              <td
                style={{
                  padding: '10px 12px',
                  borderBottom: '1px solid #eaeded',
                  textAlign: 'right',
                }}
              >
                {formatUsd(row.pfe975)}
              </td>
              <td
                style={{
                  padding: '10px 12px',
                  borderBottom: '1px solid #eaeded',
                  textAlign: 'right',
                }}
              >
                {formatUsd(row.es975)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
