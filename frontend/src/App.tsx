import { AppLayout, ContentLayout, Header, SpaceBetween } from '@cloudscape-design/components';
import '@cloudscape-design/global-styles/index.css';
import { useEffect, useState } from 'react';
import { ChatPanel } from './components/ChatPanel';
import { WhatIfForm, type WhatIfParams } from './components/WhatIfForm';
import { ApiClient, type Message } from './api/client';
import { streamAgent } from './api/stream';
import { loadSession } from './state/session';

export function App() {
  const session = loadSession();
  const [messages, setMessages] = useState<Message[]>([]);
  const [streaming, setStreaming] = useState(false);

  const apiBase = import.meta.env.VITE_API_URL as string;
  const streamBase = import.meta.env.VITE_STREAM_URL as string;
  const client = session ? new ApiClient(apiBase, session.apiKey) : null;

  useEffect(() => {
    if (!client || !session) return;
    client.listMessages(session.sessionId).then((r) => setMessages(r.messages));
  }, []);

  const handleSend = async (text: string) => {
    if (!client || !session) return;
    setStreaming(true);
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: text, turn_id: `local-${Date.now()}` },
    ]);
    let acc = '';
    setMessages((prev) => [
      ...prev,
      { role: 'assistant', content: '', turn_id: `local-asst-${Date.now()}` },
    ]);
    for await (const ev of streamAgent(streamBase, session.apiKey, session.sessionId, text)) {
      if (ev.type === 'chunk') {
        acc += ev.text;
        setMessages((prev) => {
          const next = [...prev];
          next[next.length - 1] = { ...next[next.length - 1], content: acc };
          return next;
        });
      } else if (ev.type === 'error') {
        acc += `\n[error: ${ev.message}]`;
        setMessages((prev) => {
          const next = [...prev];
          next[next.length - 1] = { ...next[next.length - 1], content: acc };
          return next;
        });
      }
    }
    setStreaming(false);
  };

  const handleApply = (p: WhatIfParams) => {
    const prompt =
      `Re-run the demo with as_of_date=${p.as_of_date}, lookback_days=${p.lookback_days}, ` +
      `horizon=${p.horizon}, n_paths=${p.n_paths}, w_stress=${p.w_stress}. ` +
      `Compare PFE against the previous run and explain the delta.`;
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
