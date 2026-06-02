import { useState, useRef, useEffect, FormEvent } from 'react';
import { Box, Button, SpaceBetween, Textarea } from '@cloudscape-design/components';
import { ImageViewer } from './ImageViewer';
import type { Message } from '../api/client';

interface ChatPanelProps {
  messages: Message[];
  onSend: (text: string) => void;
  streaming: boolean;
}

const IMAGE_RE = /!\[([^\]]*)\]\((https?:[^)]+)\)/g;

function renderContent(content: string): JSX.Element[] {
  const parts: JSX.Element[] = [];
  let last = 0;
  let key = 0;
  for (const m of content.matchAll(IMAGE_RE)) {
    if (m.index === undefined) continue;
    if (m.index > last) {
      parts.push(<span key={key++}>{content.slice(last, m.index)}</span>);
    }
    parts.push(<ImageViewer key={key++} alt={m[1]} src={m[2]} />);
    last = m.index + m[0].length;
  }
  if (last < content.length) parts.push(<span key={key++}>{content.slice(last)}</span>);
  return parts;
}

export function ChatPanel({ messages, onSend, streaming }: ChatPanelProps) {
  const [draft, setDraft] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const t = draft.trim();
    if (!t) return;
    onSend(t);
    setDraft('');
  };

  return (
    <SpaceBetween size="m">
      <div
        ref={scrollRef}
        aria-live="polite"
        style={{ maxHeight: 480, overflowY: 'auto', padding: 8, background: '#fafafa' }}
      >
        {messages.map((m) => (
          <div
            key={m.turn_id}
            style={{
              marginBottom: 12,
              padding: 8,
              background: m.role === 'user' ? '#e7f1ff' : '#fff',
              borderRadius: 4,
              border: '1px solid #e1e4ea',
            }}
          >
            <Box variant="awsui-key-label">{m.role.toUpperCase()}</Box>
            <div style={{ whiteSpace: 'pre-wrap' }}>{renderContent(m.content)}</div>
          </div>
        ))}
      </div>
      <form onSubmit={submit}>
        <SpaceBetween size="xs" direction="vertical">
          <Textarea
            value={draft}
            onChange={({ detail }) => setDraft(detail.value)}
            placeholder="Ask the copilot..."
            ariaLabel="message"
            disabled={streaming}
            rows={3}
          />
          <Button variant="primary" disabled={streaming || !draft.trim()} formAction="submit">
            Send
          </Button>
        </SpaceBetween>
      </form>
    </SpaceBetween>
  );
}
