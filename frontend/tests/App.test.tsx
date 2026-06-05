import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// Capture the prompt App passes to streamAgent, and make the session non-null
// so App constructs an ApiClient and handleApply actually fires.
const streamAgentMock = vi.fn();
vi.mock('../src/api/stream', () => ({
  streamAgent: (...args: unknown[]) => streamAgentMock(...args),
}));
vi.mock('../src/state/session', () => ({
  loadSession: () => ({ sessionId: 'sess-1', apiKey: 'key-1' }),
}));
vi.mock('../src/api/client', () => ({
  ApiClient: class {
    listMessages = vi.fn().mockResolvedValue({ messages: [] });
  },
}));

import { App } from '../src/App';

async function* emptyStream() {
  // no events — handleApply only needs the prompt it was called with
}

describe('App', () => {
  beforeEach(() => {
    streamAgentMock.mockReset();
    streamAgentMock.mockReturnValue(emptyStream());
  });

  it('renders the Numerix × Chronos-2 app shell', () => {
    render(<App />);
    // "Numerix"/"Chronos-2" appear in both the Header title and its
    // description, so use getAllByText (getByText throws on >1 match).
    expect(screen.getAllByText(/Numerix/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Chronos-2/).length).toBeGreaterThan(0);
  });

  it('shows a sidebar containing the chat panel and what-if form regions', () => {
    render(<App />);
    expect(screen.getByRole('region', { name: /chat/i })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /what-if/i })).toBeInTheDocument();
  });

  it('serializes a conditional what-if into the agent prompt', async () => {
    render(<App />);
    await userEvent.type(screen.getByLabelText(/shift_series/i), 'USDEUR');
    await userEvent.clear(screen.getByLabelText(/shift_amount/i));
    await userEvent.type(screen.getByLabelText(/shift_amount/i), '-0.1');
    await userEvent.clear(screen.getByLabelText(/n_anchor_days/i));
    await userEvent.type(screen.getByLabelText(/n_anchor_days/i), '30');
    await userEvent.click(screen.getByRole('button', { name: /apply/i }));

    const prompt = streamAgentMock.mock.calls.at(-1)?.[3] as string;
    expect(prompt).toContain('Apply a conditional what-if stress: USDEUR -0.1');
    expect(prompt).toContain('anchored over the first 30 days');
    expect(prompt).toContain('use w_stress=1 for this conditional run');
    expect(prompt).toContain('Compare PFE against the previous run');
  });

  it('omits the stress narrative from the prompt when no shift is given', async () => {
    render(<App />);
    await userEvent.click(screen.getByRole('button', { name: /apply/i }));

    const prompt = streamAgentMock.mock.calls.at(-1)?.[3] as string;
    expect(prompt).not.toContain('conditional what-if stress');
    expect(prompt).toContain('Compare PFE against the previous run');
  });
});
