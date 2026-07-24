import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const streamAgentMock = vi.fn();
const createSessionMock = vi.fn();
const saveSessionMock = vi.fn();
let storedSession: { sessionId: string; apiKey: string } | null = {
  sessionId: 'sess-1',
  apiKey: 'key-1',
};
let listedMessages: Array<{ role: 'user' | 'assistant' | 'tool'; content: string; turn_id: string }> = [];
vi.mock('../src/api/stream', () => ({
  streamAgent: (...args: unknown[]) => streamAgentMock(...args),
}));
vi.mock('../src/state/session', () => ({
  loadSession: () => storedSession,
  saveSession: (...args: unknown[]) => saveSessionMock(...args),
}));
vi.mock('../src/api/client', () => ({
  ApiClient: class {
    createSession = (...args: unknown[]) => createSessionMock(...args);
    listMessages = vi.fn().mockResolvedValue({ messages: listedMessages });
  },
}));

import { App } from '../src/App';

async function* emptyStream() {
  // no events — handleApply only needs the prompt it was called with
}

describe('App', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_API_KEY', 'configured-demo-key');
    streamAgentMock.mockReset();
    streamAgentMock.mockReturnValue(emptyStream());
    createSessionMock.mockReset();
    createSessionMock.mockResolvedValue({ session_id: 'new-session' });
    saveSessionMock.mockReset();
    storedSession = { sessionId: 'sess-1', apiKey: 'key-1' };
    listedMessages = [];
  });

  it('creates and persists a session for a fresh browser', async () => {
    storedSession = null;

    render(<App />);

    expect(screen.getByLabelText(/message/i)).toBeDisabled();
    await waitFor(() => {
      expect(createSessionMock).toHaveBeenCalledOnce();
      expect(saveSessionMock).toHaveBeenCalledWith({
        sessionId: 'new-session',
        apiKey: 'configured-demo-key',
      });
    });
    expect(screen.getByLabelText(/message/i)).toBeEnabled();
  });

  it('shows a visible error when session initialization fails', async () => {
    storedSession = null;
    createSessionMock.mockRejectedValue(new Error('401: invalid API key'));

    render(<App />);

    expect(
      await screen.findByText(/Could not connect to the demo copilot.*401/i),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/message/i)).toBeDisabled();
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
    await userEvent.type(screen.getByLabelText(/shift_series/i), 'EUR_2Y');
    await userEvent.clear(screen.getByLabelText(/shift_amount/i));
    await userEvent.type(screen.getByLabelText(/shift_amount/i), '-0.5');
    await userEvent.clear(screen.getByLabelText(/n_anchor_days/i));
    await userEvent.type(screen.getByLabelText(/n_anchor_days/i), '30');
    await userEvent.click(screen.getByRole('button', { name: /apply/i }));

    const prompt = streamAgentMock.mock.calls.at(-1)?.[3] as string;
    expect(prompt).toContain('Re-run the stage-safe setup as of 2020-03-15');
    expect(prompt).toContain('Use series shifts: EUR_2Y=-0.5; anchor 30 days.');
    expect(prompt).toContain('Compare baseline, Chronos-only, and augmented EE, PFE 97.5%, and ES 97.5%.');
    expect(prompt).not.toContain('exposure_summary');
  });

  it('omits the stress narrative from the prompt when no shift is given', async () => {
    render(<App />);
    await userEvent.click(screen.getByRole('button', { name: /apply/i }));

    const prompt = streamAgentMock.mock.calls.at(-1)?.[3] as string;
    expect(prompt).not.toContain('series shifts:');
    expect(prompt).toContain('Compare baseline, Chronos-only, and augmented EE, PFE 97.5%, and ES 97.5%.');
    expect(prompt).not.toContain('exposure_summary');
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

  it('renders structured exposure by role regardless of arrival order and keeps text, trace, and HTTPS plots', async () => {
    const exposure = (scenarioRole: 'baseline' | 'chronos_only' | 'augmented', pfe: number) => ({
      type: 'exposure_result' as const,
      executionId: 'run-1',
      specHash: 'hash-1',
      scenarioRole,
      source: scenarioRole === 'augmented' ? 'blended' : scenarioRole,
      metricsUri: `s3://metrics/${scenarioRole}.json`,
      metricsSha256: `metrics-${scenarioRole}`,
      terminal: { date: '2023-09-19', ee: pfe / 10, pfe_975: pfe, es_975: pfe * 2 },
    });

    async function* structuredStream() {
      yield {
        type: 'run_spec' as const,
        executionId: 'run-1',
        specHash: 'hash-1',
        runSpec: { profile: 'stage_safe_headline_v1', n_paths: 500 },
      };
      yield {
        type: 'tool' as const,
        toolUseId: 'load-1',
        name: 'load_data',
        status: 'running' as const,
      };
      yield {
        type: 'tool' as const,
        toolUseId: 'price-failed',
        name: 'price_book',
        status: 'failed' as const,
        result: { message: 'not a completed result' },
      };
      yield exposure('augmented', 120);
      yield exposure('chronos_only', 110);
      yield exposure('baseline', 100);
      yield {
        type: 'tool' as const,
        toolUseId: 'plot-1',
        name: 'plot',
        status: 'done' as const,
        result: {
          status: 'ok',
          result: {
            image_uri: 'https://example.com/pfe.png?X-Amz-Signature=test',
            plot_role: 'pfe_overlay',
          },
        },
      };
      yield {
        type: 'tool' as const,
        toolUseId: 'plot-2',
        name: 'plot',
        status: 'done' as const,
        result: {
          status: 'ok',
          result: {
            image_uri: 'http://example.com/insecure.png',
            plot_role: 'regime_ribbon',
          },
        },
      };
      yield { type: 'chunk' as const, text: 'Analysis complete without an exposure_summary marker.' };
      yield { type: 'done' as const };
    }
    streamAgentMock.mockReturnValue(structuredStream());

    render(<App />);
    await userEvent.type(screen.getByLabelText(/message/i), 'run demo');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));

    const trace = await screen.findByRole('region', { name: /tool trace/i });
    expect(trace).toHaveTextContent('Load data');
    expect(trace).toHaveTextContent('Failed');
    expect(screen.getByText('Baseline')).toBeInTheDocument();
    expect(screen.getByText('Chronos-only')).toBeInTheDocument();
    expect(screen.getByText('Augmented')).toBeInTheDocument();
    expect(screen.getByText('$100')).toBeInTheDocument();
    expect(screen.getByText('$110')).toBeInTheDocument();
    expect(screen.getByText('$120')).toBeInTheDocument();
    expect(screen.getByText(/\+\$20/)).toBeInTheDocument();
    expect(screen.getByText(/20\.00%/)).toBeInTheDocument();
    expect(screen.getByAltText('PFE overlay')).toHaveAttribute(
      'src',
      'https://example.com/pfe.png?X-Amz-Signature=test',
    );
    expect(screen.queryByAltText('Market regime ribbon')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: /^chat$/i })).toHaveTextContent('Analysis complete');
  });

  it('isolates executions, treats identical identities as idempotent, and surfaces conflicts', async () => {
    const exposure = (executionId: string, pfe: number, metricsSha256: string) => ({
      type: 'exposure_result' as const,
      executionId,
      specHash: `${executionId}-hash`,
      scenarioRole: 'baseline' as const,
      source: 'parametric',
      metricsUri: `s3://metrics/${executionId}.json`,
      metricsSha256,
      terminal: { date: '2023-09-19', ee: pfe, pfe_975: pfe, es_975: pfe },
    });
    async function* structuredStream() {
      yield { type: 'run_spec' as const, executionId: 'run-one', specHash: 'run-one-hash', runSpec: {} };
      yield exposure('run-one', 10, 'same');
      yield exposure('run-one', 10, 'same');
      yield exposure('run-one', 99, 'conflict');
      yield { type: 'run_spec' as const, executionId: 'run-two', specHash: 'run-two-hash', runSpec: {} };
      yield exposure('run-one', 200, 'late-run-one');
      yield exposure('run-two', 30, 'run-two-baseline');
      yield {
        type: 'exposure_result' as const,
        executionId: 'run-two',
        specHash: 'run-two-hash',
        scenarioRole: 'augmented' as const,
        source: 'blended',
        metricsUri: 's3://metrics/run-two-augmented.json',
        metricsSha256: 'run-two-augmented',
        terminal: { date: '2023-09-19', ee: 50, pfe_975: 50, es_975: 50 },
      };
    }
    streamAgentMock.mockReturnValue(structuredStream());

    render(<App />);
    await userEvent.type(screen.getByLabelText(/message/i), 'run demo');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));

    expect(await screen.findByText(/Conflicting Baseline result for execution run-one/)).toBeInTheDocument();
    expect(screen.getAllByText('$30').length).toBeGreaterThan(0);
    expect(screen.getAllByText('$50').length).toBeGreaterThan(0);
    expect(screen.queryByText('$10')).not.toBeInTheDocument();
    expect(screen.queryByText('$99')).not.toBeInTheDocument();
  });

  it('shows a raw dollar delta without a percentage when the structured baseline is zero', async () => {
    async function* structuredStream() {
      yield { type: 'run_spec' as const, executionId: 'run-zero', specHash: 'hash-zero', runSpec: {} };
      yield {
        type: 'exposure_result' as const,
        executionId: 'run-zero', specHash: 'hash-zero', scenarioRole: 'baseline' as const,
        source: 'parametric', metricsUri: 's3://metrics/zero', metricsSha256: 'zero',
        terminal: { date: '2023-09-19', ee: 0, pfe_975: 0, es_975: 0 },
      };
      yield {
        type: 'exposure_result' as const,
        executionId: 'run-zero', specHash: 'hash-zero', scenarioRole: 'augmented' as const,
        source: 'blended', metricsUri: 's3://metrics/augmented', metricsSha256: 'augmented',
        terminal: { date: '2023-09-19', ee: 15, pfe_975: 15, es_975: 15 },
      };
    }
    streamAgentMock.mockReturnValue(structuredStream());

    render(<App />);
    await userEvent.type(screen.getByLabelText(/message/i), 'run demo');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));

    expect(await screen.findByText(/\+\$15/)).toBeInTheDocument();
    expect(screen.queryByText(/Infinity%|NaN%/)).not.toBeInTheDocument();
  });
});
