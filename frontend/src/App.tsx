import {
  Alert,
  AppLayout,
  Button,
  ContentLayout,
  FormField,
  Header,
  Input,
  SpaceBetween,
} from '@cloudscape-design/components';
import '@cloudscape-design/global-styles/index.css';
import { useEffect, useRef, useState } from 'react';
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
import { clearSession, loadSession, saveSession } from './state/session';
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

function isUnauthorized(error: unknown): boolean {
  return error instanceof Error && /^\s*(401|403)(?:\s|:|$)/.test(error.message);
}

interface ArtifactIdentity {
  executionId: string;
  specHash: string;
}

function plotArtifactFromToolResult(value: unknown): PlotArtifact | null {
  const envelope = asRecord(value);
  const result = asRecord(envelope?.result) ?? envelope;
  if (
    !result ||
    typeof result.execution_id !== 'string' ||
    typeof result.spec_hash !== 'string' ||
    typeof result.plot_role !== 'string' ||
    typeof result.image_uri !== 'string' ||
    !result.image_uri.startsWith('https://') ||
    typeof result.image_sha256 !== 'string'
  ) return null;
  const labels: Record<string, string> = {
    regime_ribbon: 'Market regime ribbon',
    pfe_overlay: 'PFE overlay',
  };
  return {
    executionId: result.execution_id,
    specHash: result.spec_hash,
    plotRole: result.plot_role,
    imageSha256: result.image_sha256,
    src: result.image_uri,
    alt: labels[result.plot_role] ?? 'Generated chart',
  };
}

export function App() {
  const [session, setSession] = useState(loadSession);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [accessCode, setAccessCode] = useState('');
  const [accessError, setAccessError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const connectingRef = useRef(false);
  const connectAttemptRef = useRef(0);
  const [messages, setMessages] = useState<Message[]>([]);
  const [toolTraceEvents, setToolTraceEvents] = useState<ToolTraceEvent[]>([]);
  const [activeIdentity, setActiveIdentity] = useState<ArtifactIdentity | null>(null);
  const [runSpec, setRunSpec] = useState<RunSpecEvent | null>(null);
  const [exposureByIdentity, setExposureByIdentity] = useState<Record<string, ExposureRow>>({});
  const [hasStructuredExposure, setHasStructuredExposure] = useState(false);
  const [diagnostics, setDiagnostics] = useState<DiagnosticsEvent | null>(null);
  const [identityError, setIdentityError] = useState<string | null>(null);
  const [plotArtifacts, setPlotArtifacts] = useState<PlotArtifact[]>([]);
  const [streaming, setStreaming] = useState(false);

  const apiBase = import.meta.env.VITE_API_URL as string;
  const streamBase = import.meta.env.VITE_STREAM_URL as string;
  const client = session ? new ApiClient(apiBase, session.apiKey) : null;

  useEffect(() => {
    let cancelled = false;

    if (!session) {
      return;
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
        if (isUnauthorized(error)) {
          clearSession();
          setSession(null);
          setAccessCode('');
          setSessionError('Demo access has expired. Enter a new access code.');
          return;
        }
        const detail = error instanceof Error ? error.message : String(error);
        setSessionError(`Could not connect to the demo copilot: ${detail}`);
      });
    return () => {
      cancelled = true;
    };
  }, [apiBase, session]);

  const connect = async () => {
    if (connectingRef.current) return;
    const apiKey = accessCode.trim();
    if (!apiKey) {
      setAccessError('Enter a demo access code.');
      return;
    }

    setAccessError(null);
    setSessionError(null);
    connectingRef.current = true;
    const attempt = ++connectAttemptRef.current;
    setConnecting(true);
    try {
      const { session_id } = await new ApiClient(apiBase, apiKey).createSession();
      if (attempt !== connectAttemptRef.current) return;
      const nextSession = { sessionId: session_id, apiKey };
      saveSession(nextSession);
      setAccessCode('');
      setSession(nextSession);
    } catch {
      if (attempt === connectAttemptRef.current) {
        setSessionError('Could not connect to the demo copilot.');
      }
    } finally {
      if (attempt === connectAttemptRef.current) {
        connectingRef.current = false;
        setConnecting(false);
      }
    }
  };

  const handleSend = async (text: string) => {
    if (!client || !session) return;
    setStreaming(true);
    const priorTraceEvents = toolTraceEvents;
    const structuredTraceEvents: ToolTraceEvent[] = [];
    let boundIdentity: ArtifactIdentity | null = null;
    const admitIdentity = (identity: ArtifactIdentity, artifactName: string) => {
      if (!boundIdentity) {
        boundIdentity = identity;
        setActiveIdentity(identity);
        return true;
      }
      if (
        boundIdentity.executionId !== identity.executionId ||
        boundIdentity.specHash !== identity.specHash
      ) {
        setIdentityError(
          `Rejected ${artifactName}: execution/spec identity does not match the active run.`,
        );
        return false;
      }
      return true;
    };

    setActiveIdentity(null);
    setRunSpec(null);
    setExposureByIdentity({});
    setHasStructuredExposure(false);
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
    try {
      for await (const ev of streamAgent(streamBase, session.apiKey, session.sessionId, text)) {
      if (ev.type === 'run_spec') {
        if (admitIdentity(ev, 'run specification')) {
          setRunSpec((previous) => previous ?? ev);
        }
      } else if (ev.type === 'exposure_result') {
        setHasStructuredExposure(true);
        if (admitIdentity(ev, 'exposure result')) {
          const key = `${ev.executionId}:${ev.scenarioRole}`;
          const incoming = exposureRowFromEvent(ev);
          setExposureByIdentity((previous) => {
            const existing = previous[key];
            if (existing && existing.metricsSha256 !== incoming.metricsSha256) {
              setIdentityError(`Conflicting ${incoming.label} result for the active run.`);
              return previous;
            }
            return existing ? previous : { ...previous, [key]: incoming };
          });
        }
      } else if (ev.type === 'diagnostics') {
        if (admitIdentity(ev, 'diagnostics')) {
          setDiagnostics((previous) => {
            if (previous && previous.diagnosticsSha256 !== ev.diagnosticsSha256) {
              setIdentityError('Conflicting diagnostics result for the active run.');
              return previous;
            }
            return previous ?? ev;
          });
        }
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
          if (artifact && admitIdentity(artifact, 'plot')) {
            setPlotArtifacts((previous) => {
              const existing = previous.find((item) => item.plotRole === artifact.plotRole);
              if (existing && existing.imageSha256 !== artifact.imageSha256) {
                setIdentityError(`Conflicting ${artifact.alt} plot for the active run.`);
                return previous;
              }
              return existing ? previous : [...previous, artifact];
            });
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
    } catch (error: unknown) {
      if (isUnauthorized(error)) {
        clearSession();
        setSession(null);
        setAccessCode('');
        setSessionError('Demo access has expired. Enter a new access code.');
      }
    } finally {
      setStreaming(false);
    }
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

  const exposureRows = hasStructuredExposure
    ? Object.values(exposureByIdentity)
      .filter(
        (row) =>
          row.executionId === activeIdentity?.executionId &&
          row.specHash === activeIdentity?.specHash,
      )
      .sort((left, right) => ({ baseline: 0, chronos_only: 1, augmented: 2 }[left.scenarioRole ?? 'baseline'] - ({ baseline: 0, chronos_only: 1, augmented: 2 }[right.scenarioRole ?? 'baseline'])))
    : undefined;
  const currentRunSpec =
    runSpec?.executionId === activeIdentity?.executionId &&
    runSpec?.specHash === activeIdentity?.specHash
      ? runSpec
      : null;
  const currentDiagnostics =
    diagnostics?.executionId === activeIdentity?.executionId &&
    diagnostics?.specHash === activeIdentity?.specHash
      ? diagnostics
      : null;
  const currentPlots = plotArtifacts.filter(
    (artifact) =>
      artifact.executionId === activeIdentity?.executionId &&
      artifact.specHash === activeIdentity?.specHash,
  );

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
              {!session && (
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    void connect();
                  }}
                >
                  <SpaceBetween size="xs" direction="horizontal" alignItems="end">
                    <FormField label="Demo access code" errorText={accessError ?? undefined}>
                      <Input
                        ariaLabel="Demo access code"
                        type="password"
                        value={accessCode}
                        onChange={({ detail }) => {
                          setAccessCode(detail.value);
                          setAccessError(null);
                        }}
                        disabled={connecting}
                      />
                    </FormField>
                    <Button variant="primary" formAction="submit" loading={connecting}>
                      Connect
                    </Button>
                  </SpaceBetween>
                </form>
              )}
              {sessionError && (
                <Alert type="error" header="Connection failed">
                  {sessionError}
                </Alert>
              )}
              <ChatPanel
                messages={messages}
                onSend={handleSend}
                streaming={streaming || connecting || !session}
                images={currentPlots}
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
              <RunDetails runSpec={currentRunSpec} />
            </section>
            <section aria-label="Diagnostics" role="region">
              <Header variant="h2">Diagnostics</Header>
              <DiagnosticsPanel diagnostics={currentDiagnostics} />
            </section>
            <section aria-label="What-if" role="region">
              <Header variant="h2">What-if parameters</Header>
              <WhatIfForm onApply={handleApply} disabled={streaming || connecting || !session} />
            </section>
          </SpaceBetween>
        </ContentLayout>
      }
    />
  );
}
