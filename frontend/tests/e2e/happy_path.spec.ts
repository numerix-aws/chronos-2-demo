import { test, expect } from '@playwright/test';

const RUN = process.env.RUN_E2E === '1';
const APP_URL = process.env.APP_URL ?? '';
const API_URL = process.env.API_URL ?? '';
const STREAM_URL = process.env.STREAM_URL ?? '';
const API_KEY = process.env.API_KEY ?? '';
const HEADLINE_PROMPT =
  `Run the stage-safe headline demo for September 30, 2022. Use five years of trading history, project one trading year into the future, and generate 500 scenarios with each engine. Apply a 53.05% stress weight. Show the market regime and compare baseline exposure with Chronos-2-augmented exposure. Report the final EE, 97.5% PFE, 97.5% ES, and the PFE change.`;

const WHAT_IF_PROMPT =
  `What happens to exposure if EUR rates fall 50 basis points across the two-, five-, and ten-year tenors for the first 30 business days? Use the same stage-safe setup as the headline demo, compare baseline exposure with the conditional Chronos-2 augmentation, and show the resulting exposure profile and final EE, 97.5% PFE, and 97.5% ES.`;

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
    await expect(toolTrace).toContainText(/Load data/i, { timeout: 6 * 60 * 1000 });
    await expect(toolTrace).toContainText(/Price book/i, { timeout: 6 * 60 * 1000 });

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
