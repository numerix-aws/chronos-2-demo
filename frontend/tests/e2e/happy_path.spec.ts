import { test, expect, type Page } from '@playwright/test';
import { spawn, type ChildProcess } from 'node:child_process';
import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';

const RUN = process.env.RUN_E2E === '1';
const APP_URL = process.env.APP_URL ?? '';
const API_KEY = process.env.API_KEY ?? '';
const BUNDLE_SECRET_SENTINEL = process.env.BUNDLE_SECRET_SENTINEL ?? '';
const HEADLINE_PROMPT =
  `Run the stage-safe headline demo for September 30, 2022. Use five years of trading history, project one trading year into the future, and generate 500 scenarios with each engine. Apply a 53.05% stress weight. Show the market regime and compare baseline exposure with Chronos-2-augmented exposure. Report the final EE, 97.5% PFE, 97.5% ES, and the PFE change.`;

const WHAT_IF_PROMPT =
  `What happens to exposure if EUR rates fall 50 basis points across the two-, five-, and ten-year tenors for the first 30 business days? Use the same stage-safe setup as the headline demo, compare baseline exposure with the conditional Chronos-2 augmentation, and show the resulting exposure profile and final EE, 97.5% PFE, and 97.5% ES.`;

const LOCAL_APP_URL = process.env.LOCAL_APP_URL ?? 'http://127.0.0.1:4175';
const LOCAL_API_URL = 'https://api.local.test';
const LOCAL_STREAM_URL = 'https://stream.local.test';
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
  'base64',
);

async function appIsReady(): Promise<boolean> {
  try {
    return (await fetch(LOCAL_APP_URL)).ok;
  } catch {
    return false;
  }
}

async function waitForLocalApp(): Promise<void> {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    if (await appIsReady()) return;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Local built app did not start at ${LOCAL_APP_URL}.`);
}

async function distFiles(directory: string): Promise<string[]> {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = await Promise.all(entries.map((entry) => {
    const entryPath = path.join(directory, entry.name);
    return entry.isDirectory() ? distFiles(entryPath) : [entryPath];
  }));
  return files.flat();
}

test('built bundle excludes the access-key sentinel and VITE_API_KEY name', async () => {
  expect(BUNDLE_SECRET_SENTINEL).not.toBe('');
  const files = await distFiles(path.join(process.cwd(), 'dist'));
  expect(files.length).toBeGreaterThan(0);
  const bundle = await Promise.all(files.map((file) => readFile(file, 'utf8')));

  expect(bundle.join('\n')).not.toContain('VITE_API_KEY');
  expect(bundle.join('\n')).not.toContain(BUNDLE_SECRET_SENTINEL);
});

function plotEvent(
  toolUseId: string,
  plotRole: 'regime_ribbon' | 'pfe_overlay',
  imageUri: string,
): string {
  return JSON.stringify({
    type: 'tool',
    tool_use_id: toolUseId,
    name: 'plot',
    status: 'done',
    result: {
      status: 'ok',
      result: {
        execution_id: 'run-local',
        spec_hash: 'hash-local',
        plot_role: plotRole,
        image_uri: imageUri,
        image_sha256: `sha-${plotRole}`,
      },
    },
  });
}

async function mockLocalNetwork(page: Page) {
  await page.route('https://**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin === LOCAL_API_URL && url.pathname === '/sessions' && request.method() === 'POST') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{"session_id":"local-session"}' });
      return;
    }
    if (
      url.origin === LOCAL_API_URL &&
      url.pathname === '/sessions/local-session/messages' &&
      request.method() === 'GET'
    ) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{"messages":[]}' });
      return;
    }
    if (url.origin === LOCAL_STREAM_URL) {
      const prompt = url.searchParams.get('prompt') ?? '';
      const events = prompt.includes('failed plot')
        ? [plotEvent('plot-failed', 'pfe_overlay', 'https://plots.local.test/failed.png')]
        : [
            plotEvent('plot-regime', 'regime_ribbon', 'https://plots.local.test/regime_ribbon.png'),
            plotEvent('plot-pfe', 'pfe_overlay', 'https://plots.local.test/pfe_overlay.png'),
          ];
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        body: `${events.map((event) => `data: ${event}\n\n`).join('')}data: [DONE]\n\n`,
      });
      return;
    }
    if (url.origin === 'https://plots.local.test' && url.pathname === '/failed.png') {
      await route.fulfill({ status: 500, body: 'plot unavailable' });
      return;
    }
    if (url.origin === 'https://plots.local.test') {
      await route.fulfill({ status: 200, contentType: 'image/png', body: PNG });
      return;
    }
    await route.abort();
  });
}

test.describe('local structured plot gate', () => {
  let preview: ChildProcess | null = null;

  test.beforeAll(async () => {
    if (!(await appIsReady())) {
      preview = spawn(
        process.execPath,
        ['./node_modules/vite/bin/vite.js', 'preview', '--host', '127.0.0.1', '--port', '4175', '--strictPort'],
        { cwd: process.cwd(), stdio: 'ignore' },
      );
    }
    await waitForLocalApp();
  });

  test.afterAll(() => {
    preview?.kill('SIGTERM');
  });

  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      sessionStorage.setItem(
        'chronos2-demo-session',
        JSON.stringify({ sessionId: 'local-session', apiKey: 'local-runtime-code' }),
      );
    });
    await mockLocalNetwork(page);
  });

  test('loads both canonical direct structured plots from mocked HTTPS responses', async ({ page }) => {
    await page.goto(LOCAL_APP_URL);
    const message = page.getByLabel('message');
    await expect(message).toBeEnabled();
    await message.fill('load valid plots');
    await page.getByRole('button', { name: /^send$/i }).click();

    const plots = page.getByRole('region', { name: /chat/i }).locator('img');
    await expect(plots).toHaveCount(2);
    for (let index = 0; index < 2; index += 1) {
      await expect.poll(
        () => plots.nth(index).evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0),
      ).toBe(true);
    }
  });

  test('replaces a failed direct plot with a concise alert and no broken image', async ({ page }) => {
    await page.goto(LOCAL_APP_URL);
    const message = page.getByLabel('message');
    await expect(message).toBeEnabled();
    await message.fill('load failed plot');
    await page.getByRole('button', { name: /^send$/i }).click();

    await expect(page.getByText('PFE overlay could not be loaded.')).toBeVisible();
    await expect(page.getByRole('region', { name: /chat/i }).locator('img')).toHaveCount(0);
  });
});

test.describe('Numerix × Chronos-2 demo live happy path', () => {
  test.skip(!RUN, 'Set RUN_E2E=1 + APP_URL/API_KEY to run.');

  test.beforeEach(async ({ page }) => {
    // Runtime-only automation credentials seed the tab session after the SPA is served.
    await page.addInitScript(
      ([apiKey]) => {
        const sessionId = crypto.randomUUID();
        sessionStorage.setItem(
          'chronos2-demo-session',
          JSON.stringify({ sessionId, apiKey }),
        );
      },
      [API_KEY],
    );
  });

  test('renders the chat → streams an answer → embeds a plot image', async ({
    page,
  }) => {
    await page.goto(APP_URL);
    await expect(page.getByText(/Numerix × Chronos-2 Demo/)).toBeVisible();
    await page.waitForTimeout(3000);

    const message = page.getByLabel('message');
    await message.fill(HEADLINE_PROMPT);
    await page.getByRole('button', { name: /^send$/i }).click();

    // Streaming should produce visible assistant text within a generous window.
    const transcript = page.getByRole('region', { name: /chat/i });
    await expect(transcript).toContainText(/parametric|baseline/i, {
      timeout: 6 * 60 * 1000,
    });
    await expect(transcript).toContainText(/chronos|augment/i, {
      timeout: 6 * 60 * 1000,
    });
    await expect(transcript).toContainText(/PFE|delta/i, {
      timeout: 6 * 60 * 1000,
    });
    const toolTrace = page.getByRole('region', { name: /tool trace/i });
    await expect(toolTrace).toContainText(/Market data/i, { timeout: 6 * 60 * 1000 });
    await expect(toolTrace).toContainText(/Pricing/i, { timeout: 6 * 60 * 1000 });

    const exposureSummary = page.getByRole('region', { name: /exposure summary/i });
    await expect(exposureSummary).toContainText(/Baseline/, { timeout: 6 * 60 * 1000 });
    await expect(exposureSummary).toContainText(/Augmented/, { timeout: 6 * 60 * 1000 });
    await expect(exposureSummary).toContainText(
      /EE|PFE 97\.5%|ES 97\.5%/,
      { timeout: 6 * 60 * 1000 },
    );

    // The regime ribbon and PFE overlay must both load, not merely have an src.
    const plots = transcript.locator('img');
    await expect.poll(() => plots.count(), { timeout: 6 * 60 * 1000 }).toBeGreaterThanOrEqual(2);
    for (let i = 0; i < 2; i += 1) {
      const plot = plots.nth(i);
      await expect(plot).toBeVisible();
      const src = await plot.getAttribute('src');
      expect(src).toMatch(/X-Amz-Signature=|Signature=|AWSAccessKeyId=/);
      await expect.poll(
        () => plot.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0),
      ).toBe(true);
    }
  });

  test('natural-language what-if re-runs and updates the chart', async ({ page }) => {
    await page.goto(APP_URL);
    await page.waitForTimeout(3000);
    await page.getByLabel('message').fill(WHAT_IF_PROMPT);
    await page.getByRole('button', { name: /^send$/i }).click();
    await expect(page.getByRole('region', { name: /chat/i })).toContainText(
      /EUR|50|PFE|conditional/i,
      { timeout: 6 * 60 * 1000 },
    );
  });
});
