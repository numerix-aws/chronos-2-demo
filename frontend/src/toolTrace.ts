export type ToolTraceStatus = 'queued' | 'running' | 'done' | 'failed';

export interface ToolTraceEvent {
  id?: string;
  name: string;
  status: ToolTraceStatus;
  label?: string;
}

export type ToolTraceItem = ToolTraceEvent;

const MARKER_RE = /::tool-trace\{([^}]*)\}/g;
const LINE_MARKER_RE = /^[ \t]*::tool-trace\{[^}]*\}[ \t]*\n?/gm;
const ATTR_RE = /([A-Za-z_][\w-]*)=(?:"([^"]*)"|'([^']*)'|([^\s}]+))/g;
const STATUSES = new Set<ToolTraceStatus>(['queued', 'running', 'done', 'failed']);

function parseAttrs(raw: string): Record<string, string> {
  const attrs: Record<string, string> = {};
  for (const match of raw.matchAll(ATTR_RE)) {
    attrs[match[1]] = match[2] ?? match[3] ?? match[4] ?? '';
  }
  return attrs;
}

export function parseToolTraceEvents(text: string): ToolTraceEvent[] {
  const events: ToolTraceEvent[] = [];
  for (const match of text.matchAll(MARKER_RE)) {
    const attrs = parseAttrs(match[1]);
    const status = attrs.status as ToolTraceStatus;
    if (!attrs.name || !STATUSES.has(status)) continue;
    events.push({
      name: attrs.name,
      status,
      ...(attrs.label ? { label: attrs.label } : {}),
    });
  }
  return events;
}

export function stripToolTraceMarkers(text: string): string {
  return text
    .replace(LINE_MARKER_RE, '')
    .replace(MARKER_RE, '')
    .replace(/[ \t]+\n/g, '\n')
    .trimEnd();
}

export function reduceToolTraceEvents(events: ToolTraceEvent[]): ToolTraceItem[] {
  const byId = new Map<string, ToolTraceItem>();
  for (const event of events) {
    const id = event.id ?? event.name;
    const previous = byId.get(id);
    byId.set(id, {
      ...(event.id ? { id: event.id } : {}),
      name: event.name,
      status: event.status,
      label: event.label ?? previous?.label,
    });
  }
  return [...byId.values()];
}
