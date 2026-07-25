import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const streamAgentMock = vi.fn();
const createSessionMock = vi.fn();
const saveSessionMock = vi.fn();
const clientConstructorMock = vi.fn();
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
    constructor(...args: unknown[]) {
      clientConstructorMock(...args);
    }
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
    streamAgentMock.mockReset();
    streamAgentMock.mockReturnValue(emptyStream());
    createSessionMock.mockReset();
    createSessionMock.mockResolvedValue({ session_id: 'new-session' });
    saveSessionMock.mockReset();
    clientConstructorMock.mockReset();
    storedSession = { sessionId: 'sess-1', apiKey: 'key-1' };
    listedMessages = [];
  });

  it('does not create a session until a browser supplies a nonblank demo access code', async () => {
    storedSession = null;

    render(<App />);

    expect(screen.getByLabelText(/demo access code/i)).toHaveAttribute('type', 'password');
    expect(screen.getByLabelText(/message/i)).toBeDisabled();
    expect(screen.getByRole('button', { name: /^apply$/i })).toBeDisabled();
    expect(createSessionMock).not.toHaveBeenCalled();
    expect(saveSessionMock).not.toHaveBeenCalled();
  });

  it('rejects a blank demo access code without creating a session', async () => {
    storedSession = null;

    render(<App />);
    await userEvent.click(screen.getByRole('button', { name: /^connect$/i }));

    expect(await screen.findByText(/enter a demo access code/i)).toBeInTheDocument();
    expect(createSessionMock).not.toHaveBeenCalled();
    expect(saveSessionMock).not.toHaveBeenCalled();
    expect(screen.getByLabelText(/message/i)).toBeDisabled();
  });

  it('uses a submitted demo access code to persist and connect a session', async () => {
    storedSession = null;

    render(<App />);
    await userEvent.type(screen.getByLabelText(/demo access code/i), 'runtime-demo-code');
    await userEvent.click(screen.getByRole('button', { name: /^connect$/i }));

    await waitFor(() => {
      expect(createSessionMock).toHaveBeenCalledOnce();
      expect(clientConstructorMock.mock.calls.map(([, apiKey]) => apiKey)).toContain('runtime-demo-code');
      expect(saveSessionMock).toHaveBeenCalledWith({
        sessionId: 'new-session',
        apiKey: 'runtime-demo-code',
      });
    });
    expect(screen.getByLabelText(/message/i)).toBeEnabled();
  });

  it('keeps a failed demo access code for retry without persisting it', async () => {
    storedSession = null;
    createSessionMock.mockRejectedValueOnce(new Error('401: invalid API key'));

    render(<App />);
    const accessCode = screen.getByLabelText(/demo access code/i);
    await userEvent.type(accessCode, 'retry-demo-code');
    await userEvent.click(screen.getByRole('button', { name: /^connect$/i }));

    expect(
      await screen.findByText(/Could not connect to the demo copilot/i),
    ).toBeInTheDocument();
    expect(accessCode).toHaveValue('retry-demo-code');
    expect(saveSessionMock).not.toHaveBeenCalled();
    expect(screen.getByLabelText(/message/i)).toBeDisabled();

    createSessionMock.mockResolvedValue({ session_id: 'retry-session' });
    await userEvent.click(screen.getByRole('button', { name: /^connect$/i }));

    await waitFor(() => {
      expect(saveSessionMock).toHaveBeenCalledWith({
        sessionId: 'retry-session',
        apiKey: 'retry-demo-code',
      });
    });
    expect(screen.getByLabelText(/message/i)).toBeEnabled();
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
            execution_id: 'run-1',
            spec_hash: 'hash-1',
            image_uri: 'https://example.com/pfe.png?X-Amz-Signature=test',
            image_sha256: 'image-pfe',
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
            execution_id: 'run-1',
            spec_hash: 'hash-1',
            image_uri: 'http://example.com/insecure.png',
            image_sha256: 'image-regime',
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

  it('binds to a RunSpec first and rejects every mismatched artifact without replacing active state', async () => {
    const exposure = (
      executionId: string,
      specHash: string,
      pfe: number,
      metricsSha256: string,
    ) => ({
      type: 'exposure_result' as const,
      executionId,
      specHash,
      scenarioRole: 'baseline' as const,
      source: 'parametric',
      metricsUri: `s3://metrics/${executionId}.json`,
      metricsSha256,
      terminal: { date: '2023-09-19', ee: pfe, pfe_975: pfe, es_975: pfe },
    });
    async function* structuredStream() {
      yield {
        type: 'run_spec' as const,
        executionId: 'run-one',
        specHash: 'hash-one',
        runSpec: { profile: 'accepted-profile' },
      };
      yield exposure('run-one', 'hash-one', 10, 'same');
      yield exposure('run-one', 'hash-one', 10, 'same');
      yield exposure('run-one', 'hash-two', 99, 'same');
      yield {
        type: 'diagnostics' as const,
        executionId: 'run-two',
        specHash: 'hash-two',
        diagnosticsUri: 's3://diagnostics/rejected.json',
        diagnosticsSha256: 'diagnostics-rejected',
        diagnostics: {
          attribution: {
            uniform_chronos: { scenario_role: 'chronos_only', delta_pfe_975: 99 },
          },
        },
      };
      yield {
        type: 'tool' as const,
        toolUseId: 'plot-rejected',
        name: 'plot',
        status: 'done' as const,
        result: {
          status: 'ok',
          result: {
            execution_id: 'run-two',
            spec_hash: 'hash-two',
            image_uri: 'https://example.com/rejected.png',
            image_sha256: 'image-rejected',
            plot_role: 'pfe_overlay',
          },
        },
      };
      yield {
        type: 'run_spec' as const,
        executionId: 'run-two',
        specHash: 'run-two-hash',
        runSpec: { profile: 'rejected-profile' },
      };
    }
    streamAgentMock.mockReturnValue(structuredStream());

    render(<App />);
    await userEvent.type(screen.getByLabelText(/message/i), 'run demo');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));

    expect(
      await screen.findByText(/Rejected run specification: execution\/spec identity does not match the active run/i),
    ).toBeInTheDocument();
    expect(screen.getAllByText('$10').length).toBeGreaterThan(0);
    expect(screen.queryByText('$99')).not.toBeInTheDocument();
    expect(screen.getByText('accepted-profile')).toBeInTheDocument();
    expect(screen.queryByText('rejected-profile')).not.toBeInTheDocument();
    expect(screen.queryByText('Uniform Chronos')).not.toBeInTheDocument();
    expect(screen.queryByAltText('PFE overlay')).not.toBeInTheDocument();
  });

  it('binds to exposure before RunSpec and rejects a same-role same-hash result with another spec hash', async () => {
    async function* structuredStream() {
      yield {
        type: 'exposure_result' as const,
        executionId: 'run-exposure',
        specHash: 'hash-exposure',
        scenarioRole: 'baseline' as const,
        source: 'parametric',
        metricsUri: 's3://metrics/accepted.json',
        metricsSha256: 'same-metrics',
        terminal: { date: '2023-09-19', ee: 10, pfe_975: 10, es_975: 10 },
      };
      yield {
        type: 'run_spec' as const,
        executionId: 'run-exposure',
        specHash: 'hash-exposure',
        runSpec: { profile: 'exposure-first-profile' },
      };
      yield {
        type: 'exposure_result' as const,
        executionId: 'run-exposure',
        specHash: 'other-hash',
        scenarioRole: 'baseline' as const,
        source: 'parametric',
        metricsUri: 's3://metrics/rejected.json',
        metricsSha256: 'same-metrics',
        terminal: { date: '2023-09-19', ee: 99, pfe_975: 99, es_975: 99 },
      };
      yield {
        type: 'run_spec' as const,
        executionId: 'run-other',
        specHash: 'other-hash',
        runSpec: { profile: 'rejected-profile' },
      };
    }
    streamAgentMock.mockReturnValue(structuredStream());

    render(<App />);
    await userEvent.type(screen.getByLabelText(/message/i), 'run demo');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));

    expect(await screen.findByText('exposure-first-profile')).toBeInTheDocument();
    expect(screen.getAllByText('$10').length).toBeGreaterThan(0);
    expect(screen.queryByText('$99')).not.toBeInTheDocument();
    expect(screen.queryByText('rejected-profile')).not.toBeInTheDocument();
    expect(
      screen.getByText(/Rejected run specification: execution\/spec identity does not match the active run/i),
    ).toBeInTheDocument();
  });

  it('binds to diagnostics before RunSpec and keeps the first matching diagnostics document', async () => {
    async function* structuredStream() {
      yield {
        type: 'diagnostics' as const,
        executionId: 'run-diagnostics',
        specHash: 'hash-diagnostics',
        diagnosticsUri: 's3://diagnostics/accepted.json',
        diagnosticsSha256: 'diagnostics-accepted',
        diagnostics: {
          attribution: {
            final_blend: { scenario_role: 'augmented', delta_pfe_975: 5 },
          },
        },
      };
      yield {
        type: 'run_spec' as const,
        executionId: 'run-diagnostics',
        specHash: 'hash-diagnostics',
        runSpec: { profile: 'diagnostics-first-profile' },
      };
      yield {
        type: 'diagnostics' as const,
        executionId: 'run-diagnostics',
        specHash: 'hash-diagnostics',
        diagnosticsUri: 's3://diagnostics/conflict.json',
        diagnosticsSha256: 'diagnostics-conflict',
        diagnostics: {
          attribution: {
            uniform_chronos: { scenario_role: 'chronos_only', delta_pfe_975: 99 },
          },
        },
      };
    }
    streamAgentMock.mockReturnValue(structuredStream());

    render(<App />);
    await userEvent.type(screen.getByLabelText(/message/i), 'run demo');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));

    expect(await screen.findByText('diagnostics-first-profile')).toBeInTheDocument();
    expect(screen.getByText('Final Blend')).toBeInTheDocument();
    expect(screen.queryByText('Uniform Chronos')).not.toBeInTheDocument();
    expect(screen.getByText(/Conflicting diagnostics result for the active run/i)).toBeInTheDocument();
  });

  it('binds to a plot before RunSpec and rejects a conflicting plot without a broken mixed gallery', async () => {
    async function* structuredStream() {
      yield {
        type: 'tool' as const,
        toolUseId: 'plot-accepted',
        name: 'plot',
        status: 'done' as const,
        result: {
          status: 'ok',
          result: {
            execution_id: 'run-plot',
            spec_hash: 'hash-plot',
            image_uri: 'https://example.com/accepted.png',
            image_sha256: 'image-accepted',
            plot_role: 'pfe_overlay',
          },
        },
      };
      yield {
        type: 'run_spec' as const,
        executionId: 'run-plot',
        specHash: 'hash-plot',
        runSpec: { profile: 'plot-first-profile' },
      };
      yield {
        type: 'tool' as const,
        toolUseId: 'plot-rejected',
        name: 'plot',
        status: 'done' as const,
        result: {
          status: 'ok',
          result: {
            execution_id: 'run-plot',
            spec_hash: 'hash-plot',
            image_uri: 'https://example.com/rejected.png',
            image_sha256: 'image-rejected',
            plot_role: 'pfe_overlay',
          },
        },
      };
    }
    streamAgentMock.mockReturnValue(structuredStream());

    render(<App />);
    await userEvent.type(screen.getByLabelText(/message/i), 'run demo');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));

    expect(await screen.findByText('plot-first-profile')).toBeInTheDocument();
    expect(screen.getByAltText('PFE overlay')).toHaveAttribute(
      'src',
      'https://example.com/accepted.png',
    );
    expect(screen.queryByRole('img', { name: 'PFE overlay' })).toBeInTheDocument();
    expect(screen.getAllByRole('img')).toHaveLength(1);
    expect(screen.getByText(/Conflicting PFE overlay plot for the active run/i)).toBeInTheDocument();
  });

  it('disables legacy assistant JSON as soon as exposure arrives before RunSpec', async () => {
    listedMessages = [
      {
        role: 'assistant',
        turn_id: 'legacy',
        content: JSON.stringify({
          exposure_summary: {
            baseline: {
              date: '2023-09-19',
              ee: 9999,
              pfe_975: 9999,
              es_975: 9999,
            },
          },
        }),
      },
    ];
    async function* structuredStream() {
      yield {
        type: 'exposure_result' as const,
        executionId: 'run-structured',
        specHash: 'hash-structured',
        scenarioRole: 'baseline' as const,
        source: 'parametric',
        metricsUri: 's3://metrics/structured.json',
        metricsSha256: 'metrics-structured',
        terminal: { date: '2023-09-19', ee: 111, pfe_975: 111, es_975: 111 },
      };
    }
    streamAgentMock.mockReturnValue(structuredStream());

    render(<App />);
    expect(await screen.findAllByText('$10.0K')).toHaveLength(3);
    await userEvent.type(screen.getByLabelText(/message/i), 'run demo');
    await userEvent.click(screen.getByRole('button', { name: /send/i }));

    expect(await screen.findAllByText('$111')).toHaveLength(3);
    expect(screen.queryByText('$10.0K')).not.toBeInTheDocument();
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
