import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// Capture the prompt App passes to streamAgent, and make the session non-null
// so App constructs an ApiClient and handleApply actually fires.
const streamAgentMock = vi.fn();
let listedMessages: Array<{ role: 'user' | 'assistant' | 'tool'; content: string; turn_id: string }> = [];
vi.mock('../src/api/stream', () => ({
  streamAgent: (...args: unknown[]) => streamAgentMock(...args),
}));
vi.mock('../src/state/session', () => ({
  loadSession: () => ({ sessionId: 'sess-1', apiKey: 'key-1' }),
}));
vi.mock('../src/api/client', () => ({
  ApiClient: class {
    listMessages = vi.fn().mockResolvedValue({ messages: listedMessages });
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
    listedMessages = [];
  });

  it('renders the Numerix × Chronos-2 app shell', () => {
    render(<App />);
    // "Numerix"/"Chronos-2" appear in both the Header title and its
    // description, so use getAllByText (getByText throws on >1 match).
    expect(screen.getAllByText(/Numerix/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Chronos-2/).length).toBeGreaterThan(0);
  });

  it('shows the chat, tool trace, exposure summary, and what-if regions', () => {
    render(<App />);
    expect(screen.getByRole('region', { name: /chat/i })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /tool trace/i })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /exposure summary/i })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /what-if/i })).toBeInTheDocument();
  });

  it('surfaces EE, PFE, and ES from a structured exposure summary', async () => {
    listedMessages = [
      {
        role: 'assistant',
        turn_id: '1',
        content: JSON.stringify(
          'Run complete.\n```json exposure_summary\n' +
            JSON.stringify({
            exposure_summary: {
              baseline: {
                date: '2023-09-19',
                ee: 1200000,
                pfe_975: 4901670.11,
                es_975: 6121459.41,
              },
              augmented: {
                date: '2023-09-19',
                ee: 1450000,
                pfe_975: 5346957.61,
                es_975: 6220238.75,
              },
            },
            }) +
            '\n```',
        ),
      },
    ];

    render(<App />);

    expect(await screen.findByRole('region', { name: /exposure summary/i })).toBeInTheDocument();
    expect(screen.getByText('Baseline')).toBeInTheDocument();
    expect(screen.getByText('Augmented')).toBeInTheDocument();
    expect(screen.getByText('$1.20M')).toBeInTheDocument();
    expect(screen.getByText('$4.90M')).toBeInTheDocument();
    expect(screen.getByText('$6.22M')).toBeInTheDocument();
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
    expect(prompt).toContain('Compare EE, PFE 97.5%, and ES 97.5%');
    expect(prompt).toContain('exposure_summary');
    expect(prompt).toContain('date, ee, pfe_975, and es_975');
  });

  it('omits the stress narrative from the prompt when no shift is given', async () => {
    render(<App />);
    await userEvent.click(screen.getByRole('button', { name: /apply/i }));

    const prompt = streamAgentMock.mock.calls.at(-1)?.[3] as string;
    expect(prompt).not.toContain('conditional what-if stress');
    expect(prompt).toContain('Compare EE, PFE 97.5%, and ES 97.5%');
    expect(prompt).toContain('exposure_summary');
  });

  it('renders streamed tool trace markers outside the chat transcript', async () => {
    async function* traceStream() {
      yield {
        type: 'chunk' as const,
        text: 'Starting\n::tool-trace{name="load_data" status="running" label="Load data"}\n',
      };
      yield {
        type: 'chunk' as const,
        text: '::tool-trace{name="load_data" status="done" label="Load data"}\nDone.',
      };
    }
    streamAgentMock.mockReturnValue(traceStream());

    render(<App />);
    await userEvent.type(screen.getByLabelText(/message/i), 'run demo');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));

    const trace = await screen.findByRole('region', { name: /tool trace/i });
    expect(trace).toHaveTextContent('Load data');
    expect(trace).toHaveTextContent('Done');

    const chat = screen.getByRole('region', { name: /^chat$/i });
    expect(chat).not.toHaveTextContent('::tool-trace');
  });
});
