import { AppLayout, ContentLayout, Header, SpaceBetween } from '@cloudscape-design/components';
import '@cloudscape-design/global-styles/index.css';
import { useEffect, useState } from 'react';
import { ChatPanel } from './components/ChatPanel';
import { ExposureSummary } from './components/ExposureSummary';
import { ToolTracePanel } from './components/ToolTracePanel';
import { WhatIfForm, type WhatIfParams } from './components/WhatIfForm';
import { ApiClient, type Message } from './api/client';
import { streamAgent } from './api/stream';
import { loadSession } from './state/session';
import {
  parseToolTraceEvents,
  reduceToolTraceEvents,
  stripToolTraceMarkers,
  type ToolTraceEvent,
} from './toolTrace';

export function App() {
  const session = loadSession();
  const [messages, setMessages] = useState<Message[]>([]);
  const [toolTraceEvents, setToolTraceEvents] = useState<ToolTraceEvent[]>([]);
  const [streaming, setStreaming] = useState(false);

  const apiBase = import.meta.env.VITE_API_URL as string;
  const streamBase = import.meta.env.VITE_STREAM_URL as string;
  const client = session ? new ApiClient(apiBase, session.apiKey) : null;

  useEffect(() => {
    if (!client || !session) return;
    let cancelled = false;
    client.listMessages(session.sessionId).then((r) => {
      if (cancelled) return;
      setToolTraceEvents(r.messages.flatMap((m) => parseToolTraceEvents(m.content)));
      setMessages((prev) =>
        prev.length > 0
          ? prev
          : r.messages.map((m) => ({ ...m, content: stripToolTraceMarkers(m.content) })),
      );
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSend = async (text: string) => {
    if (!client || !session) return;
    setStreaming(true);
    const priorTraceEvents = toolTraceEvents;
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
      if (ev.type === 'chunk') {
        rawAcc += ev.text;
        setToolTraceEvents([...priorTraceEvents, ...parseToolTraceEvents(rawAcc)]);
        const visibleText = stripToolTraceMarkers(rawAcc);
        setMessages((prev) => {
          const next = [...prev];
          next[next.length - 1] = { ...next[next.length - 1], content: visibleText };
          return next;
        });
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
      `Re-run the demo with as_of_date=${p.as_of_date}, lookback_days=${p.lookback_days}, ` +
      `horizon=${p.horizon}, n_paths=${p.n_paths}, w_stress=${p.w_stress}. `;
    if (p.conditioning) {
      const shifts = Object.entries(p.conditioning.series_shifts)
        .map(([k, val]) => `${k} ${val >= 0 ? '+' : ''}${val}`)
        .join(', ');
      prompt +=
        `Apply a conditional what-if stress: ${shifts} anchored over the first ` +
        `${p.conditioning.n_anchor_days} days (use w_stress=1 for this conditional run). `;
    }
    prompt +=
      'Compare EE, PFE 97.5%, and ES 97.5% against the previous run and explain the delta. ' +
      'End with a fenced json block named exposure_summary using raw numeric dollar values, ' +
      'with previous and current objects containing date, ee, pfe_975, and es_975.';
    void handleSend(prompt);
  };

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
              <ChatPanel messages={messages} onSend={handleSend} streaming={streaming} />
            </section>
            <section aria-label="Tool trace" role="region">
              <Header variant="h2">Tool trace</Header>
              <ToolTracePanel items={reduceToolTraceEvents(toolTraceEvents)} />
            </section>
            <section aria-label="Exposure summary" role="region">
              <Header variant="h2">Exposure summary</Header>
              <ExposureSummary messages={messages} />
            </section>
            <section aria-label="What-if" role="region">
              <Header variant="h2">What-if parameters</Header>
              <WhatIfForm onApply={handleApply} disabled={streaming} />
            </section>
          </SpaceBetween>
        </ContentLayout>
      }
    />
  );
}
