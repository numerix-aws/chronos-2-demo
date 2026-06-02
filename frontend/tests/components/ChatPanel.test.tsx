import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
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
  });
});
