import { Alert, AppLayout, Box, ContentLayout, Header, SpaceBetween } from '@cloudscape-design/components';
import '@cloudscape-design/global-styles/index.css';
import { useEffect, useState } from 'react';
import { ChatPanel, type PlotArtifact } from './components/ChatPanel';
import {
  ExposureSummary,
  exposureRowFromEvent,
  type ExposureRow,
} from './components/ExposureSummary';
import { RunDetails } from './components/RunDetails';
import { DiagnosticsPanel } from './components/DiagnosticsPanel';
import { ToolTracePanel } from './components/ToolTracePanel';
import { WhatIfForm, type WhatIfParams } from './components/WhatIfForm';
import { ApiClient, type Message } from './api/client';
import {
  streamAgent,
  type DiagnosticsEvent,
  type ExposureResultEvent,
  type RunSpecEvent,
} from './api/stream';
import { loadSession, saveSession } from './state/session';
import {
  parseToolTraceEvents,
  reduceToolTraceEvents,
  stripToolTraceMarkers,
  type ToolTraceEvent,
} from './toolTrace';

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function plotArtifactFromToolResult(value: unknown): PlotArtifact | null {
  const envelope = asRecord(value);
  const result = asRecord(envelope?.result) ?? envelope;
  if (!result || typeof result.image_uri !== 'string' || !result.image_uri.startsWith('https://')) return null;
  const labels: Record<string, string> = {
    regime_ribbon: 'Market regime ribbon',
    pfe_overlay: 'PFE overlay',
  };
  const role = typeof result.plot_role === 'string' ? result.plot_role : 'plot';
  return { src: result.image_uri, alt: labels[role] ?? 'Generated chart' };
}

export function App() {
  const [session, setSession] = useState(loadSession);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [toolTraceEvents, setToolTraceEvents] = useState<ToolTraceEvent[]>([]);
  const [runSpec, setRunSpec] = useState<RunSpecEvent | null>(null);
  const [exposureByIdentity, setExposureByIdentity] = useState<Record<string, ExposureRow>>({});
  const [diagnostics, setDiagnostics] = useState<DiagnosticsEvent | null>(null);
  const [identityError, setIdentityError] = useState<string | null>(null);
  const [plotArtifacts, setPlotArtifacts] = useState<PlotArtifact[]>([]);
  const [streaming, setStreaming] = useState(false);

  const apiBase = import.meta.env.VITE_API_URL as string;
  const streamBase = import.meta.env.VITE_STREAM_URL as string;
  const configuredApiKey = (import.meta.env.VITE_API_KEY as string | undefined)?.trim();
  const client = session ? new ApiClient(apiBase, session.apiKey) : null;

  const acceptExposure = (event: ExposureResultEvent) => {
    const key = `${event.executionId}:${event.scenarioRole}`;
    const incoming = exposureRowFromEvent(event);
    setExposureByIdentity((previous) => {
      const existing = previous[key];
      if (existing && existing.metricsSha256 !== incoming.metricsSha256) {
        setIdentityError(`Conflicting ${incoming.label} result for execution ${event.executionId}.`);
        return previous;
      }
      return existing ? previous : { ...previous, [key]: incoming };
    });
  };

  useEffect(() => {
    let cancelled = false;

    if (!session) {
      if (!configuredApiKey) {
        setSessionError('Could not connect to the demo copilot: API key is not configured.');
        return;
      }
      new ApiClient(apiBase, configuredApiKey)
        .createSession()
        .then(({ session_id }) => {
          if (cancelled) return;
          const nextSession = { sessionId: session_id, apiKey: configuredApiKey };
          saveSession(nextSession);
          setSession(nextSession);
        })
        .catch((error: unknown) => {
          if (cancelled) return;
          const detail = error instanceof Error ? error.message : String(error);
          setSessionError(`Could not connect to the demo copilot: ${detail}`);
        });
      return () => {
        cancelled = true;
      };
    }

    const activeClient = new ApiClient(apiBase, session.apiKey);
    activeClient
      .listMessages(session.sessionId)
      .then((r) => {
        if (cancelled) return;
        setSessionError(null);
        setToolTraceEvents(r.messages.flatMap((m) => parseToolTraceEvents(m.content)));
        setMessages((prev) =>
          prev.length > 0
            ? prev
            : r.messages.map((m) => ({ ...m, content: stripToolTraceMarkers(m.content) })),
        );
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const detail = error instanceof Error ? error.message : String(error);
        setSessionError(`Could not connect to the demo copilot: ${detail}`);
      });
    return () => {
      cancelled = true;
    };
  }, [apiBase, configuredApiKey, session]);

  const handleSend = async (text: string) => {
    if (!client || !session) return;
    setStreaming(true);
    const priorTraceEvents = toolTraceEvents;
    const structuredTraceEvents: ToolTraceEvent[] = [];
    setRunSpec(null);
    setExposureByIdentity({});
    setDiagnostics(null);
    setIdentityError(null);
    setPlotArtifacts([]);
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: text, turn_id: `local-${Date.now()}` },
    ]);
    let rawAcc = '';
    setMessages((prev) => [
      ...prev,
      { role: 'assistant', content: '', turn_id: `local-asst-${Date.now()}` },
    ]);
    for await (const ev of streamAgent(streamBase, session.apiKey, session.sessionId, text)) {
      if (ev.type === 'run_spec') {
        setRunSpec(ev);
      } else if (ev.type === 'exposure_result') {
        acceptExposure(ev);
      } else if (ev.type === 'diagnostics') {
        setDiagnostics(ev);
      } else if (ev.type === 'chunk') {
        rawAcc += ev.text;
        setToolTraceEvents([
          ...priorTraceEvents,
          ...structuredTraceEvents,
          ...parseToolTraceEvents(rawAcc),
        ]);
        const visibleText = stripToolTraceMarkers(rawAcc);
        setMessages((prev) => {
          const next = [...prev];
          next[next.length - 1] = { ...next[next.length - 1], content: visibleText };
          return next;
        });
      } else if (ev.type === 'tool') {
        structuredTraceEvents.push({
          id: ev.toolUseId,
          name: ev.name,
          status: ev.status,
        });
        setToolTraceEvents([
          ...priorTraceEvents,
          ...structuredTraceEvents,
          ...parseToolTraceEvents(rawAcc),
        ]);
        if (ev.status === 'done' && ev.name === 'plot') {
          const artifact = plotArtifactFromToolResult(ev.result);
          if (artifact) {
            setPlotArtifacts((prev) =>
              prev.some((item) => item.src === artifact.src) ? prev : [...prev, artifact],
            );
          }
        }
      } else if (ev.type === 'error') {
        rawAcc += `\n[error: ${ev.message}]`;
        setMessages((prev) => {
          const next = [...prev];
          next[next.length - 1] = { ...next[next.length - 1], content: rawAcc };
          return next;
        });
      }
    }
    setStreaming(false);
  };

  const handleApply = (p: WhatIfParams) => {
    let prompt =
      `Re-run the stage-safe setup as of ${p.as_of_date}. Look back ${p.lookback_days} ` +
      `trading days, project ${p.horizon} trading days into the future, generate ` +
      `${p.n_paths} scenarios with each engine, and apply a stress weight of ${p.w_stress}. `;
    if (p.conditioning) {
      const shifts = Object.entries(p.conditioning.series_shifts)
        .map(([name, value]) => `${name}=${value}`)
        .join(', ');
      prompt += `Use series shifts: ${shifts}; anchor ${p.conditioning.n_anchor_days} days. `;
    }
    prompt += 'Compare baseline, Chronos-only, and augmented EE, PFE 97.5%, and ES 97.5%.';
    void handleSend(prompt);
  };

  const exposureRows = runSpec
    ? Object.values(exposureByIdentity)
      .filter((row) => row.executionId === runSpec.executionId)
      .sort((left, right) => ({ baseline: 0, chronos_only: 1, augmented: 2 }[left.scenarioRole ?? 'baseline'] - ({ baseline: 0, chronos_only: 1, augmented: 2 }[right.scenarioRole ?? 'baseline'])))
    : undefined;
  const currentDiagnostics = diagnostics?.executionId === runSpec?.executionId ? diagnostics : null;

  return (
    <AppLayout
      navigationHide
      toolsHide
      content={
        <ContentLayout
          header={
            <Header variant="h1" description="Chronos-2 augmenting the Numerix Monte Carlo">
              Numerix × Chronos-2 Demo
            </Header>
          }
        >
          <SpaceBetween size="l">
            <section aria-label="Chat" role="region">
              <Header variant="h2">Conversation</Header>
              {!session && !sessionError && (
                <Box color="text-status-info">Connecting to the demo copilot...</Box>
              )}
              {sessionError && (
                <Alert type="error" header="Connection failed">
                  {sessionError}
                </Alert>
              )}
              <ChatPanel
                messages={messages}
                onSend={handleSend}
                streaming={streaming || !session}
                images={plotArtifacts}
              />
            </section>
            <section aria-label="Tool trace" role="region">
              <Header variant="h2">Tool trace</Header>
              <ToolTracePanel items={reduceToolTraceEvents(toolTraceEvents)} />
            </section>
            <section aria-label="Exposure summary" role="region">
              <Header variant="h2">Exposure summary</Header>
              <ExposureSummary messages={messages} rows={exposureRows} />
              {identityError && <Alert type="error">{identityError}</Alert>}
            </section>
            <section aria-label="Run details" role="region">
              <Header variant="h2">Run details</Header>
              <RunDetails runSpec={runSpec} />
            </section>
            <section aria-label="Diagnostics" role="region">
              <Header variant="h2">Diagnostics</Header>
              <DiagnosticsPanel diagnostics={currentDiagnostics} />
            </section>
            <section aria-label="What-if" role="region">
              <Header variant="h2">What-if parameters</Header>
              <WhatIfForm onApply={handleApply} disabled={streaming || !session} />
            </section>
          </SpaceBetween>
        </ContentLayout>
      }
    />
  );
}
