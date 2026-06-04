# Plan B — Part 10: Stage 10 — Wire what-if conditioning end-to-end

> **Continuation of** `2026-05-22-plan-b-ux-agent-part-9.md`. Tasks 27–31.
>
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the interactive what-if beat (spec §3 beat 4, §6 conditional generation) work live through the copilot/UI, not just the notebook — by wiring the Plan A `Conditioning` support through the four layers that don't yet carry it.

**Architecture:** The Plan A core (`chronos2_client.Conditioning` + `simulate_chronos2(conditioning=…)`) already supports conditional generation, and the `run_chronos2` Lambda handler already forwards an optional `conditioning` event field to the Fargate task as `CONDITIONING_JSON`. Three layers are missing it: the **Fargate entrypoint** never reads `CONDITIONING_JSON`; the **agent `action_groups.json`** doesn't advertise a `conditioning` arg; the **system prompt** what-if beat only mentions `w_stress`/`as_of`; and the **frontend `WhatIfForm`** has no stress-shift inputs. This stage closes all four.

**Tech Stack:** Python 3.11 (Fargate entrypoint), JSON (action groups), Markdown (system prompt), React 18 + TypeScript + Cloudscape + vitest (frontend).

**Reference spec:** `docs/superpowers/specs/2026-05-22-numerix-chronos2-poc-design.md` (§3 beat 4, §6, §7). **Depends on:** Plan B Stages 0–9 complete.

---

> **Executor's Contract:** Plan B's contract (part-1) still applies — tool contracts are integration points; don't widen schemas beyond what a task specifies; no live AWS calls in unit tests. One reinforcement for this stage:
> - **The `conditioning` field is optional everywhere.** Every layer must behave exactly as today when it is absent — an unconditional run. Only when present does it flow through to `simulate_chronos2`.

---

## File Structure (touched in this stage)

```
tools/fargate/run_chronos2/entrypoint.py   # MODIFY: read CONDITIONING_JSON → Conditioning
tools/lambda/run_chronos2/handler.py       # (NO CHANGE — already forwards conditioning)
agent/action_groups.json                   # MODIFY: run_chronos2 gains optional conditioning
agent/system_prompt.md                     # MODIFY: what-if beat describes series shifts
frontend/src/components/WhatIfForm.tsx      # MODIFY: optional stress-shift rows
frontend/src/App.tsx                        # MODIFY: serialize conditioning into the prompt
tools/tests/test_run_chronos2_entrypoint.py # MODIFY: assert conditioning is parsed + passed
agent/tests/test_action_groups.py          # MODIFY: assert conditioning schema shape
frontend/src/components/WhatIfForm.test.tsx # MODIFY/CREATE: assert shift rows emit conditioning
```

---

## Stage 10 — Conditioning wiring

### Task 27: Fargate entrypoint reads CONDITIONING_JSON

**Files:**
- Modify: `tools/fargate/run_chronos2/entrypoint.py`
- Test: `tools/tests/test_run_chronos2_entrypoint.py` (modify)

The entrypoint builds a `Conditioning` from the `CONDITIONING_JSON` env var (when set) and passes it to `simulate_chronos2`. Shape: `{"series_shifts": {col: float}, "n_anchor_days": int}` — exactly `Conditioning.to_jsonable()`. This closes the one open follow-up tracked in project memory.

- [ ] **Step 1: Write the failing test**

Append to `tools/tests/test_run_chronos2_entrypoint.py`:
```python
def test_entrypoint_parses_conditioning_and_passes_it(s3, monkeypatch):
    import json
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("PANEL_URI", "s3://test-data/lb.parquet")
    monkeypatch.setenv("AS_OF", "2022-06-23")
    monkeypatch.setenv("HORIZON", "21")
    monkeypatch.setenv("N_PATHS", "50")
    monkeypatch.setenv("OUTPUT_KEY", "sessions/abc/chronos2.pkl")
    monkeypatch.setenv("CHRONOS2_ENDPOINT", "chronos2-demo-ep")
    monkeypatch.setenv("CONDITIONING_JSON",
                       json.dumps({"series_shifts": {"USDEUR": -0.1}, "n_anchor_days": 30}))
    _seed_panel(s3)

    fake_ps = PathSet(
        paths=np.zeros((50, 21, 3), dtype=float),
        weights=np.full(50, 1.0 / 50),
        series=["USDEUR", "USDJPY", "USD_5Y"],
        dates=pd.bdate_range("2022-06-24", periods=21),
        source="chronos2_conditional",
    )
    ep = _load_entrypoint()
    with patch.object(ep.sagemaker_endpoint, "open_endpoint", return_value=object()), \
         patch.object(ep.chronos2_client, "simulate_chronos2", return_value=fake_ps) as m:
        ep.main()

    _, kwargs = m.call_args
    cond = kwargs["conditioning"]
    assert cond is not None
    assert cond.series_shifts == {"USDEUR": -0.1}
    assert cond.n_anchor_days == 30
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tools/tests/test_run_chronos2_entrypoint.py::test_entrypoint_parses_conditioning_and_passes_it -v
```
Expected: FAIL (`KeyError: 'conditioning'` — `simulate_chronos2` is called without it).

- [ ] **Step 3: Implement**

In `tools/fargate/run_chronos2/entrypoint.py`, add `import json` at the top with the other stdlib imports, then build the conditioning between the covariates block and the `simulate_chronos2` call:
```python
    conditioning = None
    if os.environ.get("CONDITIONING_JSON"):
        payload = json.loads(os.environ["CONDITIONING_JSON"])
        conditioning = chronos2_client.Conditioning(
            series_shifts={k: float(v) for k, v in payload.get("series_shifts", {}).items()},
            n_anchor_days=int(payload.get("n_anchor_days", 0)),
        )
```
and pass it in the `simulate_chronos2(...)` call (add the kwarg after `covariates=covariates,`):
```python
        covariates=covariates,
        conditioning=conditioning,
        seed=seed,
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tools/tests/test_run_chronos2_entrypoint.py -v
```
Expected: PASS (both the new test and the existing unconditional/`bad_horizon` tests — `conditioning` defaults to `None`).

- [ ] **Step 5: Commit**

```bash
git add tools/fargate/run_chronos2/entrypoint.py tools/tests/test_run_chronos2_entrypoint.py
git commit -m "feat(fargate): run_chronos2 entrypoint reads CONDITIONING_JSON for what-if

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 28: Advertise `conditioning` in the agent tool schema

**Files:**
- Modify: `agent/action_groups.json` (the `/run_chronos2` requestBody schema)
- Test: `agent/tests/test_action_groups.py` (modify)

Add an optional `conditioning` object to `run_chronos2`'s input schema so the agent (and the Gateway) knows the field exists. It stays out of `required`.

- [ ] **Step 1: Write the failing test**

Append to `agent/tests/test_action_groups.py`:
```python
def test_run_chronos2_advertises_optional_conditioning():
    spec = _load()
    schema = spec["paths"]["/run_chronos2"]["post"]["requestBody"][
        "content"]["application/json"]["schema"]
    cond = schema["properties"]["conditioning"]
    assert cond["type"] == "object"
    assert "series_shifts" in cond["properties"]
    assert cond["properties"]["n_anchor_days"]["type"] == "integer"
    # Optional: not in the required list.
    assert "conditioning" not in schema.get("required", [])
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest agent/tests/test_action_groups.py::test_run_chronos2_advertises_optional_conditioning -v
```
Expected: FAIL (`KeyError: 'conditioning'`).

- [ ] **Step 3: Implement**

In `agent/action_groups.json`, in `/run_chronos2` → `post` → `requestBody` → schema → `properties`, add after the `covariates_uri` property (sibling of it; `required` stays `["session_id", "panel_uri", "as_of", "horizon", "n_paths"]`):
```json
                  "covariates_uri": { "type": "string", "format": "uri" },
                  "conditioning": {
                    "type": "object",
                    "description": "Optional what-if stress narrative. series_shifts maps a panel column to an additive level shift applied over the first n_anchor_days of the horizon.",
                    "properties": {
                      "series_shifts": {
                        "type": "object",
                        "additionalProperties": { "type": "number" }
                      },
                      "n_anchor_days": { "type": "integer", "minimum": 1, "maximum": 1000 }
                    },
                    "required": ["series_shifts", "n_anchor_days"]
                  }
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest agent/tests/test_action_groups.py -v
```
Expected: PASS (all existing schema/validity tests still green — `check_schema` accepts the nested object).

- [ ] **Step 5: Commit**

```bash
git add agent/action_groups.json agent/tests/test_action_groups.py
git commit -m "feat(agent): run_chronos2 tool schema advertises optional conditioning

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 29: System prompt describes the conditional what-if

**Files:**
- Modify: `agent/system_prompt.md`
- Test: none (prose; covered by the agent's behavior, not a unit test) — verify with a grep in Step 2.

Teach the agent that the what-if beat can pass `conditioning` to `run_chronos2`, and the `w_stress = 1` convention for an explicit conditional stress scenario (spec §6).

- [ ] **Step 1: Edit the prompt**

In `agent/system_prompt.md`, replace the beat-5 line (line 13):
```markdown
5. **What-if** — two flavors. (a) Re-weighting what-if: accept a new `w_stress` or `as_of` and re-run from step 3. (b) **Conditional what-if** (spec §6 beat 4): when the user describes a stress narrative (e.g. "EUR rates +100bp and USD/JPY −10% over 30 days"), call `run_chronos2` with a `conditioning` object — `series_shifts` mapping each affected panel column to an additive level shift, and `n_anchor_days` for how many days the shift anchors. Treat a conditional run as an explicit stress scenario: blend it with `w_stress = 1`.
```
And update the `run_chronos2` line in the Tools list (line 22) to advertise the field:
```markdown
- `run_chronos2(session_id, panel_uri, as_of, horizon, n_paths, [covariates_uri], [conditioning])` → `{task_arn, paths_uri}` *(async — launches Fargate; `conditioning = {series_shifts:{col:shift}, n_anchor_days:int}` for what-if)*
```

- [ ] **Step 2: Verify the edits landed**

```bash
grep -n "Conditional what-if\|conditioning = {series_shifts\|w_stress = 1" agent/system_prompt.md
```
Expected: three matching lines.

- [ ] **Step 3: Commit**

```bash
git add agent/system_prompt.md
git commit -m "docs(agent): system prompt describes the conditional what-if beat

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 30: Frontend what-if form emits conditioning

**Files:**
- Modify: `frontend/src/components/WhatIfForm.tsx`
- Modify: `frontend/src/App.tsx:56-62` (`handleApply`)
- Test: `frontend/tests/components/WhatIfForm.test.tsx` (modify)

Add an optional single stress-shift row (series name + additive shift) and an `n_anchor_days` input to the form. When the user fills the series field, `onApply` receives a `conditioning` object; otherwise it's omitted (unconditional, unchanged behavior). `App.handleApply` serializes it into the natural-language prompt the agent parses.

- [ ] **Step 1: Write the failing test**

Append to `frontend/tests/components/WhatIfForm.test.tsx` (inside the `describe`):
```tsx
  it('emits conditioning when a shift series is provided', async () => {
    const onApply = vi.fn();
    render(<WhatIfForm onApply={onApply} disabled={false} />);
    await userEvent.type(screen.getByLabelText(/shift_series/i), 'USDEUR');
    await userEvent.clear(screen.getByLabelText(/shift_amount/i));
    await userEvent.type(screen.getByLabelText(/shift_amount/i), '-0.1');
    await userEvent.clear(screen.getByLabelText(/n_anchor_days/i));
    await userEvent.type(screen.getByLabelText(/n_anchor_days/i), '30');
    await userEvent.click(screen.getByRole('button', { name: /apply/i }));
    expect(onApply).toHaveBeenCalledWith(
      expect.objectContaining({
        conditioning: { series_shifts: { USDEUR: -0.1 }, n_anchor_days: 30 },
      }),
    );
  });

  it('omits conditioning when no shift series is provided', async () => {
    const onApply = vi.fn();
    render(<WhatIfForm onApply={onApply} disabled={false} />);
    await userEvent.click(screen.getByRole('button', { name: /apply/i }));
    expect(onApply).toHaveBeenCalledWith(
      expect.not.objectContaining({ conditioning: expect.anything() }),
    );
  });
```

- [ ] **Step 2: Run, confirm fail**

```bash
cd frontend && npx vitest run tests/components/WhatIfForm.test.tsx
```
Expected: FAIL (no `shift_series` label; `conditioning` never emitted).

- [ ] **Step 3: Implement**

In `frontend/src/components/WhatIfForm.tsx`, extend the `WhatIfParams` interface:
```tsx
export interface WhatIfParams {
  as_of_date: string;
  lookback_days: number;
  horizon: number;
  n_paths: number;
  w_stress: number;
  conditioning?: { series_shifts: Record<string, number>; n_anchor_days: number };
}
```
Add three control fields to the state initializer (alongside the existing keys), as plain strings outside the `WhatIfParams` keyed record — use a second state object:
```tsx
  const [cond, setCond] = useState({ shift_series: '', shift_amount: '0', n_anchor_days: '30' });
```
In `submit`, after the existing validation passes and before `onApply({...})`, build the optional conditioning and include it:
```tsx
    const base = {
      as_of_date: v.as_of_date,
      lookback_days: lb,
      horizon: hz,
      n_paths: np,
      w_stress: w,
    };
    if (cond.shift_series.trim() !== '') {
      const amt = parseFloat(cond.shift_amount);
      const nad = parseInt(cond.n_anchor_days, 10);
      if (Number.isNaN(amt) || !(nad > 0)) {
        setErr('shift_amount must be numeric and n_anchor_days a positive integer');
        return;
      }
      onApply({
        ...base,
        conditioning: { series_shifts: { [cond.shift_series.trim()]: amt }, n_anchor_days: nad },
      });
      return;
    }
    onApply(base);
```
(Remove the original `onApply({...})` block that this replaces.) Add the three inputs inside the `<ColumnLayout>`, after the existing fields:
```tsx
            <FormField label="shift_series">
              <Input value={cond.shift_series} ariaLabel="shift_series"
                onChange={({ detail }) => setCond({ ...cond, shift_series: detail.value })} />
            </FormField>
            <FormField label="shift_amount">
              <Input value={cond.shift_amount} type="number" ariaLabel="shift_amount"
                onChange={({ detail }) => setCond({ ...cond, shift_amount: detail.value })} />
            </FormField>
            <FormField label="n_anchor_days">
              <Input value={cond.n_anchor_days} type="number" ariaLabel="n_anchor_days"
                onChange={({ detail }) => setCond({ ...cond, n_anchor_days: detail.value })} />
            </FormField>
```

In `frontend/src/App.tsx`, replace `handleApply` (lines 56-62) so the conditioning reaches the agent prompt:
```tsx
  const handleApply = (p: WhatIfParams) => {
    let prompt =
      `Re-run the demo with as_of_date=${p.as_of_date}, lookback_days=${p.lookback_days}, ` +
      `horizon=${p.horizon}, n_paths=${p.n_paths}, w_stress=${p.w_stress}. `;
    if (p.conditioning) {
      const shifts = Object.entries(p.conditioning.series_shifts)
        .map(([k, val]) => `${k} ${val >= 0 ? '+' : ''}${val}`)
        .join(', ');
      prompt +=
        `Apply a conditional what-if stress: ${shifts} anchored over the first ` +
        `${p.conditioning.n_anchor_days} days (use w_stress=1 for this conditional run). `;
    }
    prompt += `Compare PFE against the previous run and explain the delta.`;
    void handleSend(prompt);
  };
```

- [ ] **Step 4: Run, confirm pass**

```bash
cd frontend && npx vitest run tests/components/WhatIfForm.test.tsx
```
Expected: PASS (new conditioning tests + the four existing WhatIfForm tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/WhatIfForm.tsx frontend/src/App.tsx frontend/tests/components/WhatIfForm.test.tsx
git commit -m "feat(frontend): what-if form emits optional conditioning to the agent

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 31: Price the cross-asset book in the `price_book` Lambda

**Files:**
- Modify: `tools/lambda/price_book/handler.py:41-42`
- Test: `tools/tests/test_price_book.py` (modify)

The agent's `price_book` tool currently calls `load_book` + `compute_metrics(book, ps)` — swap-only. After Plan A part-4 Task 34, `load_cross_asset_book` + `compute_metrics(..., equity_forwards=, cds_protection=)` price the equity forward and CDS proxy too. Without this, the live agent demo would silently price swaps-only while the notebook prices the full cross-asset book — breaking the "same engine, different inputs" claim exactly where the partner sees it. (Depends on Plan A part-4 Task 34 being merged.)

- [ ] **Step 1: Update the test to seed cross-asset series**

In `tools/tests/test_price_book.py`, extend the `series` list in `_seed_pathset` so the equity/credit instruments have columns to read:
```python
    series = ["USDEUR", "USDJPY", "USDGBP", "USD_5Y", "EUR_5Y", "JPY_5Y", "GBP_5Y",
              "SPX", "NIKKEI225", "US_IG_OAS", "US_HY_OAS"]
```
And add a test asserting the handler's PFE matches the *cross-asset* book, not the swap-only book — the discriminating check:
```python
def test_price_book_prices_cross_asset_not_swaps_only(s3, monkeypatch):
    import numpy as np
    from chronos2_demo.pricing import book as bk, exposure
    monkeypatch.setenv("DATA_BUCKET", "test-data")
    monkeypatch.setenv("BOOK_PATH", str(DEFAULT_BOOK_PATH))
    uri = _seed_pathset(s3, "test-data", "ps.pkl")
    ps = handler._download_pickle(uri)
    out = handler.handler({"paths_uri": uri, "book_id": "demo"}, None)
    handler_pfe = np.array(out["result"]["pfe_975"])

    swaps, eq, cds = bk.load_cross_asset_book(str(DEFAULT_BOOK_PATH))
    full = exposure.compute_metrics(swaps, ps, equity_forwards=eq, cds_protection=cds)["pfe_975"]
    swaps_only = exposure.compute_metrics(swaps, ps)["pfe_975"]
    # The handler must match the full cross-asset book, and that must differ
    # from the swap-only computation (proves equity+credit are priced).
    np.testing.assert_allclose(handler_pfe, full, rtol=1e-9)
    assert not np.allclose(full, swaps_only)
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tools/tests/test_price_book.py::test_price_book_prices_cross_asset_not_swaps_only -v
```
Expected: FAIL — the handler still calls `load_book` + swap-only `compute_metrics`, so `handler_pfe` matches `swaps_only`, not `full`; the `assert_allclose(handler_pfe, full)` fails.

> **Dependency:** this task requires Plan A part-4 Task 34 (`load_cross_asset_book` + `compute_metrics` instrument kwargs). If that hasn't merged, `load_cross_asset_book` is absent — stop and confirm it landed first.

- [ ] **Step 3: Update the handler**

In `tools/lambda/price_book/handler.py`, replace lines 41-42:
```python
    # The demo book ships in the Lambda layer; BOOK_PATH is set by Task 13.
    swaps, equity_forwards, cds_protection = book_mod.load_cross_asset_book(
        os.environ["BOOK_PATH"])
    metrics = exposure.compute_metrics(
        swaps, ps, equity_forwards=equity_forwards, cds_protection=cds_protection)
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tools/tests/test_price_book.py -v
```
Expected: PASS (both existing tests + the cross-asset assertion).

- [ ] **Step 5: Commit**

```bash
git add tools/lambda/price_book/handler.py tools/tests/test_price_book.py
git commit -m "feat(tools): price_book Lambda values the full cross-asset book

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Plan B part-10 complete

After Task 31 the what-if conditioning path is wired end-to-end:
- Frontend form → natural-language prompt with the stress narrative.
- Agent (`run_chronos2` schema + system prompt) → `conditioning` tool arg.
- Lambda handler (unchanged) → `CONDITIONING_JSON` env var.
- Fargate entrypoint → `Conditioning` → `simulate_chronos2(conditioning=…)`.

The interactive what-if beat (spec §3 beat 4) now runs live through the copilot/UI, not only in the notebook. This closes the conditioning follow-up deferred since Plan B part-4.

> _End of Plan B (part-10)._

