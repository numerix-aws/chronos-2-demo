import { test, expect } from '@playwright/test';

const RUN = process.env.RUN_E2E === '1';
const APP_URL = process.env.APP_URL ?? '';
const API_URL = process.env.API_URL ?? '';
const STREAM_URL = process.env.STREAM_URL ?? '';
const API_KEY = process.env.API_KEY ?? '';

test.skip(!RUN, 'Set RUN_E2E=1 + APP_URL/API_URL/STREAM_URL/API_KEY to run.');

test.describe('Numerix × Chronos-2 demo happy path', () => {
  test.beforeEach(async ({ page }) => {
    // Seed localStorage so the SPA picks up an existing session and the API key
    // without a login flow (the demo has none).
    await page.addInitScript(
      ([apiKey, apiUrl, streamUrl]) => {
        const sessionId = crypto.randomUUID();
        localStorage.setItem(
          'chronos2-demo-session',
          JSON.stringify({ sessionId, apiKey }),
        );
        // Vite reads these at runtime via import.meta.env, so we patch globals.
        (window as any).__VITE_API_URL__ = apiUrl;
        (window as any).__VITE_STREAM_URL__ = streamUrl;
      },
      [API_KEY, API_URL, STREAM_URL],
    );
  });

  test('renders the chat → streams an answer → embeds a plot image', async ({
    page,
  }) => {
    await page.goto(APP_URL);
    await expect(page.getByText(/Numerix × Chronos-2 Demo/)).toBeVisible();

    const message = page.getByLabel('message');
    await message.fill(
      'Run the headline demo at as_of_date=2020-03-15, lookback_days=1260, ' +
        'horizon=252, n_paths=2000, w_stress=0.5. Then plot a PFE overlay.',
    );
    await page.getByRole('button', { name: /^send$/i }).click();

    // Streaming should produce visible assistant text within a generous window.
    const transcript = page.getByRole('region', { name: /chat/i });
    await expect(transcript).toContainText(/parametric|baseline/i, {
      timeout: 4 * 60 * 1000,
    });
    await expect(transcript).toContainText(/chronos|augment/i, {
      timeout: 4 * 60 * 1000,
    });

    // The plot image must point at our plots bucket via a presigned URL.
    const plot = transcript.locator('img').first();
    await expect(plot).toBeVisible({ timeout: 4 * 60 * 1000 });
    const src = await plot.getAttribute('src');
    expect(src).toMatch(/X-Amz-Signature=/);
  });

  test('what-if form re-runs and updates the chart', async ({ page }) => {
    await page.goto(APP_URL);
    await page.getByLabel('w_stress').fill('0.8');
    await page.getByRole('button', { name: /apply/i }).click();
    await expect(page.getByRole('region', { name: /chat/i })).toContainText(
      /w_stress=0\.8/,
      { timeout: 4 * 60 * 1000 },
    );
  });
});
