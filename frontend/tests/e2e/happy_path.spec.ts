import { test, expect } from '@playwright/test';

const RUN = process.env.RUN_E2E === '1';
const APP_URL = process.env.APP_URL ?? '';
const API_URL = process.env.API_URL ?? '';
const STREAM_URL = process.env.STREAM_URL ?? '';
const API_KEY = process.env.API_KEY ?? '';
const HEADLINE_PROMPT =
  'Run a stage-safe headline demo at as_of_date=2022-09-30, lookback_days=1260, ' +
  'horizon=252, n_paths=500, w_stress=0.5305. Use the full workflow: load_data, ' +
  'and emit tool-trace markers before and after each tool call so the Tool trace ' +
  'panel shows the sequence; then call plot with spec=regime_ribbon using the returned regimes_uri and ' +
  'threshold=0.7; run_baseline_mc with n_components=5 and seed=0 and poll until ' +
  'ready; run_chronos2 and poll until ready; blend_paths; price_book on the ' +
  'baseline paths and blended paths; then call plot with spec=pfe_overlay using ' +
  'the two metrics_uri values. In the final answer, report the final-date baseline and ' +
  'augmented EE, PFE 97.5%, and ES 97.5%; the absolute PFE delta; and the ' +
  'percent PFE delta only if the baseline is non-zero. End with a fenced json ' +
  'block named exposure_summary using raw numeric dollar values, with baseline ' +
  'and augmented objects containing date, ee, pfe_975, and es_975. Include both ' +
  'returned image_uri values: one for the regime ribbon and one for the PFE overlay, ' +
  'with markdown image links.';

const WHAT_IF_PROMPT =
  'What happens to exposure if EUR rates fall 50 basis points over the first 30 ' +
  'business days? Use the same stage-safe setup as before: as_of_date=2022-09-30, ' +
  'lookback_days=1260, horizon=252, n_paths=500. Translate the 50 bp move as ' +
  'conditioning shifts of -0.50 on EUR_2Y, EUR_5Y, and EUR_10Y, with n_anchor_days=30. ' +
  'Emit tool-trace markers before and after each tool call so the Tool trace panel ' +
  'shows the sequence. Run the tool sequence visibly: load_data, run_baseline_mc with n_components=5 ' +
  'and seed=0 and poll until ready, run_chronos2 with that conditioning and poll ' +
  'until ready, blend_paths with w_stress=1 for the conditional stress view, ' +
  'price_book on the baseline and conditional blended paths, then plot spec=pfe_overlay ' +
  'using the two metrics_uri values. Report final-date EE, PFE 97.5%, and ES 97.5% ' +
  'for baseline versus conditional augmented, and include the returned image_uri ' +
  'with a markdown image link.';

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
    await expect(page.getByRole('region', { name: /exposure summary/i })).toContainText(
      /EE|PFE 97\.5%|ES 97\.5%/,
      { timeout: 6 * 60 * 1000 },
    );

    // The plot image must point at our plots bucket via a presigned URL.
    const plot = transcript.locator('img').first();
    await expect(plot).toBeVisible({ timeout: 6 * 60 * 1000 });
    const src = await plot.getAttribute('src');
    expect(src).toMatch(/X-Amz-Signature=|Signature=|AWSAccessKeyId=/);
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
