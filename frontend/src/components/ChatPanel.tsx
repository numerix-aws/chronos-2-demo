import { useState, useRef, useEffect, FormEvent } from 'react';
import { Box, Button, SpaceBetween, Textarea } from '@cloudscape-design/components';
import Markdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ImageViewer } from './ImageViewer';
import type { Message } from '../api/client';

interface ChatPanelProps {
  messages: Message[];
  onSend: (text: string) => void;
  streaming: boolean;
  images?: PlotArtifact[];
}

export interface PlotArtifact {
  src: string;
  alt: string;
}

const markdownComponents: Components = {
  h1: ({ children }) => (
    <h3 style={{ fontSize: 18, lineHeight: '24px', margin: '0 0 8px' }}>{children}</h3>
  ),
  h2: ({ children }) => (
    <h4 style={{ fontSize: 16, lineHeight: '22px', margin: '12px 0 6px' }}>{children}</h4>
  ),
  h3: ({ children }) => (
    <h5 style={{ fontSize: 15, lineHeight: '20px', margin: '12px 0 6px' }}>{children}</h5>
  ),
  p: ({ children }) => <div style={{ margin: '0 0 8px' }}>{children}</div>,
  ul: ({ children }) => <ul style={{ margin: '4px 0 10px', paddingLeft: 22 }}>{children}</ul>,
  ol: ({ children }) => <ol style={{ margin: '4px 0 10px', paddingLeft: 22 }}>{children}</ol>,
  li: ({ children }) => <li style={{ marginBottom: 3 }}>{children}</li>,
  table: ({ children }) => (
    <div style={{ overflowX: 'auto', margin: '8px 0 12px' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th
      style={{
        border: '1px solid #c6cbd4',
        background: '#f2f3f3',
        padding: '6px 8px',
        textAlign: 'left',
      }}
    >
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td style={{ border: '1px solid #d5d9d9', padding: '6px 8px', verticalAlign: 'top' }}>
      {children}
    </td>
  ),
  code: ({ children }) => (
    <code
      style={{
        background: '#f2f3f3',
        borderRadius: 3,
        fontSize: '0.92em',
        padding: '1px 4px',
      }}
    >
      {children}
    </code>
  ),
  pre: ({ children }) => (
    <pre style={{ overflowX: 'auto', margin: '8px 0', padding: 10, background: '#f2f3f3' }}>
      {children}
    </pre>
  ),
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer">
      {children}
    </a>
  ),
  img: ({ alt, src }) => (src ? <ImageViewer alt={alt ?? ''} src={src} /> : null),
  hr: () => <hr style={{ border: 0, borderTop: '1px solid #d5d9d9', margin: '12px 0' }} />,
};

function renderContent(message: Message, directImageUris: Set<string>): JSX.Element | string {
  if (message.role !== 'assistant') return message.content;
  return (
    <Markdown
      remarkPlugins={[remarkGfm]}
      components={{
        ...markdownComponents,
        img: ({ alt, src }) =>
          src && !directImageUris.has(src) ? <ImageViewer alt={alt ?? ''} src={src} /> : null,
      }}
    >
      {message.content}
    </Markdown>
  );
}

export function ChatPanel({ messages, onSend, streaming, images = [] }: ChatPanelProps) {
  const [draft, setDraft] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);
  const directImageUris = new Set(images.map((item) => item.src));

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, images]);

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
            <div style={{ whiteSpace: m.role === 'assistant' ? 'normal' : 'pre-wrap' }}>
              {renderContent(m, directImageUris)}
            </div>
          </div>
        ))}
        {images.map((item) => (
          <ImageViewer key={item.src} alt={item.alt} src={item.src} />
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
