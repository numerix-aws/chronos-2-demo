import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatPanel } from '../../src/components/ChatPanel';

describe('ChatPanel', () => {
  it('renders prior messages from props', () => {
    render(
      <ChatPanel
        messages={[
          { role: 'user', content: 'hi', turn_id: '1' },
          { role: 'assistant', content: 'hello', turn_id: '2' },
        ]}
        onSend={vi.fn()}
        streaming={false}
      />,
    );
    expect(screen.getByText('hi')).toBeInTheDocument();
    expect(screen.getByText('hello')).toBeInTheDocument();
  });

  it('calls onSend with typed text and clears the input', async () => {
    const onSend = vi.fn();
    render(<ChatPanel messages={[]} onSend={onSend} streaming={false} />);
    const input = screen.getByLabelText(/message/i) as HTMLTextAreaElement;
    await userEvent.type(input, 'run baseline');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));
    expect(onSend).toHaveBeenCalledWith('run baseline');
    await waitFor(() => expect(input.value).toBe(''));
  });

  it('disables the send button while streaming', () => {
    render(<ChatPanel messages={[]} onSend={vi.fn()} streaming={true} />);
    expect(screen.getByRole('button', { name: /send/i })).toBeDisabled();
  });

  it('renders an inline image when assistant content has a markdown image', () => {
    render(
      <ChatPanel
        messages={[
          {
            role: 'assistant',
            content: 'Here is the chart ![pfe](https://example.com/p.png)',
            turn_id: '1',
          },
        ]}
        onSend={vi.fn()}
        streaming={false}
      />,
    );
    const img = screen.getByAltText('pfe') as HTMLImageElement;
    expect(img.src).toBe('https://example.com/p.png');
    expect(img.loading).toBe('eager');
  });

  it('renders assistant Markdown as formatted content', () => {
    render(
      <ChatPanel
        messages={[
          {
            role: 'assistant',
            content:
              '# Copilot online\n\n**Ready** to run `load_data`.\n\n| Step | Tool |\n|---|---|\n| 1 | load_data |',
            turn_id: '1',
          },
        ]}
        onSend={vi.fn()}
        streaming={false}
      />,
    );

    expect(screen.getByRole('heading', { name: 'Copilot online' })).toBeInTheDocument();
    expect(screen.getByText('Ready').tagName).toBe('STRONG');
    expect(screen.getByRole('table')).toBeInTheDocument();
  });

  it('replaces a failed plot with a concise error instead of a broken image', async () => {
    render(
      <ChatPanel
        messages={[]}
        images={[{
          executionId: 'run-1',
          specHash: 'hash-1',
          plotRole: 'pfe_overlay',
          imageSha256: 'image-1',
          alt: 'PFE overlay',
          src: 'https://example.com/pfe.png',
        }]}
        onSend={vi.fn()}
        streaming={false}
      />,
    );

    fireEvent.error(screen.getByAltText('PFE overlay'));

    expect(await screen.findByText(/PFE overlay could not be loaded/i)).toBeInTheDocument();
    expect(screen.queryByAltText('PFE overlay')).not.toBeInTheDocument();
  });
});
