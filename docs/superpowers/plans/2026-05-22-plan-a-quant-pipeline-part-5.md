# Plan A — Part 5: Stage 13 — All-live market data sources + S3 seeding

> **Continuation of** `2026-05-22-plan-a-quant-pipeline-part-4.md`. Tasks 40–47.
>
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Plan A data layer pull **live** market data that actually works against today's public endpoints, so the demo runs on real data spanning ~2015→present including the 2020 COVID stress. The shipped fetchers were written against endpoints that have since changed and **silently fail on the live path** (verified 2026-06-05): FRED's unkeyed CSV endpoint is rate-limited, the ECB host moved and is EUR-base-only, MOVE was never a FRED series, equity series are capped/sparse on FRED, and ICE BofA credit OAS is licence-locked to a rolling ~3-year window. This part rewires each source and adds an S3 seeding script so the deployed tools can read the curated panel.

**Architecture:** Keep the existing fetch/align/regime contracts intact (the `PathSet`, the 19-column panel, the percent-unit credit columns, the `w_stress` regimes frame). Only the *source plumbing* changes:
- **FRED** → keyed JSON API (`api.stlouisfed.org/fred/series/observations`), `observation_start=2015-01-01`. The api_key (currently ignored) becomes load-bearing.
- **ECB FX** → new host `data-api.ecb.europa.eu`; ECB publishes only EUR-base rates, so non-EUR USD pairs are derived by **triangulation** (`USD{CCY} = D.USD.EUR / D.{CCY}.EUR`).
- **Equity + MOVE** → Yahoo Finance chart API (`query1.finance.yahoo.com/v8/finance/chart/{symbol}`), which reaches 2015 for `^GSPC`, `^N225`, `^MOVE`.
- **Credit OAS** → free deep FRED proxy `BAA10Y` (Moody's Baa−10Y Treasury, daily to 1986). `US_IG_OAS ← BAA10Y`; `US_HY_OAS ← 1.7 × BAA10Y`. Columns keep their names + percent units; **semantics change** (proxy, not ICE OAS).
- **`snapshot_data.py`** emits `regimes.parquet` (derived from the panel) alongside `panel`/`covariates`; a new **`seed_demo_data.py`** uploads all three to the S3 data bucket the Lambda tools read.

**Tech Stack:** Python 3.11, numpy, pandas, requests, boto3. `moto[s3]` (already in the `dev` extra) for the seeding test. No new dependencies.

**Reference spec:** `docs/superpowers/specs/2026-05-22-numerix-chronos2-poc-design.md` (§3 data layer; 2026-06-05 live-data banner).

---

> **Before Task 40:** read the **Engineering Discipline** section in `CLAUDE.md`. Plan-A-specific reinforcements still apply, plus four for this part:
> - **Tests stay hermetic.** Every fetcher test mocks `requests.get` (the existing `@patch("chronos2_demo.data.fetch.requests.get")` style); no live network in the suite. `snapshot_data.py` is a network entrypoint and is intentionally **not** unit-tested — verify it by running it live.
> - **The frozen regression fixture is untouchable.** `tests/fixtures/headline_panel.parquet` + `tests/fixtures/build_headline_panel.py` + `tests/test_headline_numbers.py` are fully synthetic and independent of live fetch. **Do not touch them.** If a change here would force them to change, you've broken a contract — stop.
> - **Credit columns are a relabeled proxy, in percent.** `US_IG_OAS`/`US_HY_OAS` keep their names and percent units (so `pricing/instruments.py:57` and the pricing tests hold), but now represent a Baa−Treasury-based proxy. Say so in docstrings + commit messages. This is sanctioned (user decision 2026-06-05), not a bug to "fix."
> - **Don't widen scope.** This part only rewires data sources + adds seeding. Do not change `config.py` demo defaults, the pricing math, or the FX *column set*. A pre-existing EUR-base FX-convention nuance is addressed only insofar as triangulation requires it.

---

## File Structure (locked in before tasks)

```
src/chronos2_demo/
├── data/
│   ├── fetch.py            # MODIFY: keyed FRED JSON; ECB host+triangulation; +fetch_yahoo_series; credit→BAA10Y proxy
│   └── covariates.py       # MODIFY: MOVE→Yahoo; thread api_key through load_covariates/_fetch_one
scripts/
├── snapshot_data.py        # MODIFY: equities→Yahoo, FX→triangulation, pass api_key, emit regimes.parquet
└── seed_demo_data.py       # CREATE: upload panel/covariates/regimes parquets to the S3 data bucket
tests/
└── data/
    ├── test_fetch.py       # MODIFY: FRED JSON mock; ECB host assert; +Yahoo test; +triangulation test; credit→BAA10Y
    └── test_covariates.py  # MODIFY: +test_fetch_one_move_uses_yahoo
tools/tests/
└── test_seed_demo_data.py  # CREATE: moto s3 round-trip
```

**Verified live facts (ground truth, 2026-06-05) — do not re-litigate:**
- Keyed FRED JSON returns `DGS2/DGS10/DBAA/DAAA/BAA10Y/VIXCLS/DCOILWTICO` cleanly from 2015 (count ~2981). Unkeyed `fredgraph.csv` returns 0 lines (rate-limited).
- ECB live host `https://data-api.ecb.europa.eu/service/data/EXR/D.{base}.{quote}.SP00.A?format=csvdata`; `D.USD.EUR`✓, `D.{JPY,GBP,CHF,CAD}.EUR`✓, but `D.USD.{JPY,GBP,CHF,CAD}` → 404. CSV cols include `TIME_PERIOD`,`OBS_VALUE` by name. Old host `sdw-wsrest.ecb.europa.eu` is dead.
- Yahoo `^GSPC`,`^N225`,`^MOVE`,`^VIX` reach 2015 via `query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1=..&period2=..&interval=1d` with `User-Agent: Mozilla/5.0`. JSON: `.chart.result[0].timestamp[]` (epoch s) + `.indicators.quote[0].close[]`.
- `BAA10Y`: calm(2019)≈2.42, COVID-peak(2020-03-23)≈4.31. `DBAA−DAAA`: calm≈0.99, peak≈1.50.
- Triangulation orientation (panel = USD-per-foreign): `USDEUR = D.USD.EUR`; `USD{CCY} = D.USD.EUR / D.{CCY}.EUR`. Checked: 1.2043/145.21 ≈ 0.00829 ≈ USDJPY base 0.0088. ✓

---

## Stage 13 — All-live market data

The shipped fetchers target dead/changed endpoints. Rewire each source behind the existing function contracts, add regimes emission to the snapshot, and add an S3 seeding script.

### Task 40: Switch `fetch_fred_series` to the keyed JSON API

**Files:**
- Modify: `src/chronos2_demo/data/fetch.py` (`fetch_fred_series`)
- Test: `tests/data/test_fetch.py` (modify)

The function builds a keyed-JSON `params` dict but then ignores it and GETs `fredgraph.csv` (now rate-limited → empty). Make it actually use the keyed JSON endpoint (`FRED_CSV_URL` already points at `.../fred/series/observations`), pass `observation_start`, and parse `resp.json()["observations"]`.

- [ ] **Step 1: Rewrite the failing test**

In `tests/data/test_fetch.py`, add a JSON-response helper next to `_fake_csv_response` (keep the CSV one — the ECB test still uses it):
```python
def _fake_json_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp
```

Replace `test_fetch_fred_series_returns_dated_floats` with:
```python
@patch("chronos2_demo.data.fetch.requests.get")
def test_fetch_fred_series_returns_dated_floats(mock_get):
    mock_get.return_value = _fake_json_response({
        "observations": [
            {"date": "2022-01-03", "value": "1.63"},
            {"date": "2022-01-04", "value": "1.66"},
            {"date": "2022-01-05", "value": "."},
        ]
    })
    s = fetch.fetch_fred_series("DGS10", api_key="fake")
    assert s.index[0] == pd.Timestamp("2022-01-03")
    assert s.iloc[0] == pytest.approx(1.63)
    assert len(s) == 2  # "." row dropped
    # uses the keyed JSON endpoint, passes api_key + observation_start
    args, kwargs = mock_get.call_args
    assert args[0] == fetch.FRED_CSV_URL
    assert kwargs["params"]["api_key"] == "fake"
    assert kwargs["params"]["file_type"] == "json"
    assert kwargs["params"]["observation_start"] == "2015-01-01"
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/data/test_fetch.py::test_fetch_fred_series_returns_dated_floats -v
```
Expected: FAIL (current impl calls `fredgraph.csv` / parses CSV, so `params`/endpoint asserts fail and `resp.json` isn't consulted).

- [ ] **Step 3: Implement**

Replace the body of `fetch_fred_series` in `src/chronos2_demo/data/fetch.py`:
```python
OBS_START = "2015-01-01"


def fetch_fred_series(series_id: str, api_key: str) -> pd.Series:
    """Fetch a FRED series as a daily Series via the keyed JSON API."""
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": OBS_START,
    }
    resp = requests.get(FRED_CSV_URL, params=params, timeout=30)
    resp.raise_for_status()
    obs = resp.json()["observations"]
    rows = [(o["date"], o["value"]) for o in obs if o["value"] != "."]
    idx = pd.to_datetime([d for d, _ in rows])
    s = pd.Series([float(v) for _, v in rows], index=idx, name=series_id)
    return s
```
(Leave `FRED_CSV_URL = "https://api.stlouisfed.org/fred/series/observations"` and `import io` as-is — ECB still uses `io`.)

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/data/test_fetch.py -v
```
Expected: PASS (the credit test still passes — it monkeypatches `fetch_fred_series` wholesale; it is rewritten in Task 44).

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/data/fetch.py tests/data/test_fetch.py
git commit -m "fix(data): fetch FRED via keyed JSON API (unkeyed CSV endpoint is rate-limited)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 41: Point ECB FX at the live host

**Files:**
- Modify: `src/chronos2_demo/data/fetch.py` (`ECB_CSV_URL`)
- Test: `tests/data/test_fetch.py` (modify the ECB test)

The host `sdw-wsrest.ecb.europa.eu` is dead (http 000). The live host is `data-api.ecb.europa.eu`. The CSV parse is unchanged (it selects `TIME_PERIOD`/`OBS_VALUE` by name, which the new format still provides).

- [ ] **Step 1: Extend the failing test**

In `tests/data/test_fetch.py`, add a host assertion to `test_fetch_ecb_fx_returns_dated_floats` (after the existing asserts):
```python
    assert mock_get.call_args.args[0].startswith(
        "https://data-api.ecb.europa.eu/service/data/EXR"
    )
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/data/test_fetch.py::test_fetch_ecb_fx_returns_dated_floats -v
```
Expected: FAIL (`AssertionError` — still the old host).

- [ ] **Step 3: Implement**

In `src/chronos2_demo/data/fetch.py`, change the constant:
```python
ECB_CSV_URL = "https://data-api.ecb.europa.eu/service/data/EXR"
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/data/test_fetch.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/data/fetch.py tests/data/test_fetch.py
git commit -m "fix(data): point ECB FX fetcher at data-api.ecb.europa.eu (old host dead)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 42: Add `fetch_yahoo_series` (Yahoo chart API)

**Files:**
- Modify: `src/chronos2_demo/data/fetch.py` (new function)
- Test: `tests/data/test_fetch.py` (new test)

Equity (`^GSPC`,`^N225`) and MOVE (`^MOVE`) come from Yahoo. The index must be **tz-naive midnight** so it inner-joins with the FRED/ECB date-only indices in `align_panel` (otherwise the join silently drops everything).

- [ ] **Step 1: Write the failing test**

Append to `tests/data/test_fetch.py`:
```python
@patch("chronos2_demo.data.fetch.requests.get")
def test_fetch_yahoo_series_returns_dated_floats(mock_get):
    mock_get.return_value = _fake_json_response({
        "chart": {"result": [{
            "timestamp": [1420243200, 1420329600, 1420416000],
            "indicators": {"quote": [{"close": [2058.2, 2020.6, None]}]},
        }]}
    })
    s = fetch.fetch_yahoo_series("^GSPC")
    assert s.name == "^GSPC"
    assert s.iloc[0] == pytest.approx(2058.2)
    assert len(s) == 2  # None close dropped
    assert s.index.tz is None
    assert s.index[0] == s.index[0].normalize()  # midnight
    args, kwargs = mock_get.call_args
    assert args[0] == "https://query1.finance.yahoo.com/v8/finance/chart/^GSPC"
    assert kwargs["params"]["interval"] == "1d"
    assert kwargs["headers"]["User-Agent"].startswith("Mozilla")
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/data/test_fetch.py::test_fetch_yahoo_series_returns_dated_floats -v
```
Expected: FAIL (`AttributeError: module ... has no attribute 'fetch_yahoo_series'`).

- [ ] **Step 3: Implement**

Append to `src/chronos2_demo/data/fetch.py`:
```python
import time

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
_OBS_START_EPOCH = int(time.mktime(time.strptime(OBS_START, "%Y-%m-%d")))


def fetch_yahoo_series(symbol: str) -> pd.Series:
    """Fetch a Yahoo Finance daily close series as a tz-naive dated Series."""
    params = {"period1": _OBS_START_EPOCH, "period2": int(time.time()),
              "interval": "1d"}
    resp = requests.get(f"{YAHOO_CHART_URL}/{symbol}", params=params,
                        headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    resp.raise_for_status()
    r = resp.json()["chart"]["result"][0]
    ts = r["timestamp"]
    close = r["indicators"]["quote"][0]["close"]
    idx = pd.to_datetime(ts, unit="s").normalize()
    s = pd.Series(close, index=idx, name=symbol).dropna()
    return s
```
(`time.time()` is fine here — this is a live network entrypoint, never run in the hermetic suite, where `requests.get` is mocked.)

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/data/test_fetch.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/data/fetch.py tests/data/test_fetch.py
git commit -m "feat(data): add Yahoo chart-API fetcher for equity + MOVE series

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 43: Triangulate non-EUR USD FX pairs

**Files:**
- Modify: `src/chronos2_demo/data/fetch.py` (`fetch_ecb_fx`)
- Test: `tests/data/test_fetch.py` (new test)

ECB publishes only EUR-base rates, so `D.USD.JPY` etc. 404. The panel stores **USD-per-foreign** (`USDJPY≈0.0088`). Derive crosses from EUR-base rates: `USDEUR = D.USD.EUR`; for any other foreign ccy `F`, `USD{F} = (USD per EUR) / (F per EUR) = D.USD.EUR / D.F.EUR`. Make `fetch_ecb_fx(base, quote)` handle the `base="USD"` case by fetching the two EUR-base legs and dividing; keep the direct path for `quote="EUR"`.

The existing `test_fetch_ecb_fx_returns_dated_floats` calls `fetch_ecb_fx("EUR","USD")` (a direct EUR-base key `D.EUR.USD...`) — that still works as a single direct fetch and stays green. The new behavior is specifically for `base="USD", quote!="EUR"`.

- [ ] **Step 1: Write the failing test**

Append to `tests/data/test_fetch.py`:
```python
@patch("chronos2_demo.data.fetch.requests.get")
def test_fetch_ecb_fx_triangulates_usd_crosses(mock_get):
    # Two EUR-base legs: USD per EUR, then JPY per EUR.
    mock_get.side_effect = [
        _fake_csv_response("TIME_PERIOD,OBS_VALUE\n2015-01-02,1.2043\n"),
        _fake_csv_response("TIME_PERIOD,OBS_VALUE\n2015-01-02,145.21\n"),
    ]
    s = fetch.fetch_ecb_fx("USD", "JPY")
    assert s.name == "USDJPY"
    # USD per JPY = (USD/EUR) / (JPY/EUR)
    assert s.iloc[0] == pytest.approx(1.2043 / 145.21, rel=1e-6)
    # first leg is the USD/EUR key, second is the JPY/EUR key
    first_url = mock_get.call_args_list[0].args[0]
    second_url = mock_get.call_args_list[1].args[0]
    assert "D.USD.EUR.SP00.A" in first_url
    assert "D.JPY.EUR.SP00.A" in second_url
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/data/test_fetch.py::test_fetch_ecb_fx_triangulates_usd_crosses -v
```
Expected: FAIL (current code builds a single `D.USD.JPY.SP00.A` key → one fetch, wrong name/value).

- [ ] **Step 3: Implement**

Replace `fetch_ecb_fx` in `src/chronos2_demo/data/fetch.py`:
```python
def _fetch_ecb_eur_base(quote_ccy: str) -> pd.Series:
    """Fetch one EUR-base ECB daily rate: units of quote_ccy per 1 EUR."""
    url = f"{ECB_CSV_URL}/D.{quote_ccy}.EUR.SP00.A?format=csvdata"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df["TIME_PERIOD"] = pd.to_datetime(df["TIME_PERIOD"])
    return df.set_index("TIME_PERIOD")["OBS_VALUE"].astype(float)


def fetch_ecb_fx(base_ccy: str, quote_ccy: str) -> pd.Series:
    """USD-per-foreign FX. ECB is EUR-base only, so USD crosses are triangulated.

    base="USD": USD{quote} = (USD per EUR) / (quote per EUR).  quote="EUR"
    is the direct USD/EUR leg.
    """
    if base_ccy == "USD":
        usd_per_eur = _fetch_ecb_eur_base("USD")
        if quote_ccy == "EUR":
            s = usd_per_eur
        else:
            quote_per_eur = _fetch_ecb_eur_base(quote_ccy)
            s = (usd_per_eur / quote_per_eur).dropna()
        s.name = f"{base_ccy}{quote_ccy}"
        return s
    # Legacy direct path (e.g. EUR/USD) — single key.
    flow_key = f"D.{base_ccy}.{quote_ccy}.SP00.A"
    url = f"{ECB_CSV_URL}/{flow_key}?format=csvdata"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df["TIME_PERIOD"] = pd.to_datetime(df["TIME_PERIOD"])
    s = df.set_index("TIME_PERIOD")["OBS_VALUE"].astype(float)
    s.name = f"{base_ccy}{quote_ccy}"
    return s
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/data/test_fetch.py -v
```
Expected: PASS (both the legacy EUR/USD test and the new triangulation test).

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/data/fetch.py tests/data/test_fetch.py
git commit -m "fix(data): triangulate USD FX crosses from ECB EUR-base rates

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 44: Source credit OAS from the `BAA10Y` proxy

**Files:**
- Modify: `src/chronos2_demo/data/fetch.py` (`fetch_credit_oas`)
- Test: `tests/data/test_fetch.py` (rewrite the credit test)

ICE BofA OAS (`BAMLC0A0CM`/`BAMLH0A0HYM2`) is licence-locked to 2023-06 on FRED — unrecoverable, no ALFRED archive. Use the deep free proxy `BAA10Y` (Moody's Baa minus 10Y Treasury, daily to 1986, in percent): `US_IG_OAS ← BAA10Y`, `US_HY_OAS ← _HY_MULTIPLE × BAA10Y` (`_HY_MULTIPLE = 1.7`, lands HY near the ~4.0 base). Columns keep names + percent units; **semantics change** (sanctioned proxy).

- [ ] **Step 1: Rewrite the failing test**

Replace `test_fetch_credit_oas_maps_names_to_fred_ids` in `tests/data/test_fetch.py`:
```python
def test_fetch_credit_oas_uses_baa10y_proxy(monkeypatch):
    from chronos2_demo.data import fetch
    captured = []

    def fake_fred(series_id, api_key):
        captured.append(series_id)
        return pd.Series([2.4, 2.5],
                         index=pd.to_datetime(["2022-06-01", "2022-06-02"]),
                         name=series_id)

    monkeypatch.setattr(fetch, "fetch_fred_series", fake_fred)
    ig = fetch.fetch_credit_oas("US_IG_OAS", api_key="k")
    hy = fetch.fetch_credit_oas("US_HY_OAS", api_key="k")
    assert captured == ["BAA10Y", "BAA10Y"]      # both legs proxy off BAA10Y
    assert ig.name == "US_IG_OAS" and hy.name == "US_HY_OAS"
    assert ig.iloc[0] == pytest.approx(2.4)       # IG = BAA10Y
    assert hy.iloc[0] == pytest.approx(2.4 * fetch._HY_MULTIPLE)
    assert (hy > ig).all()                        # HY strictly wider
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/data/test_fetch.py::test_fetch_credit_oas_uses_baa10y_proxy -v
```
Expected: FAIL (`_HY_MULTIPLE` missing; current impl pulls `BAMLC0A0CM`/`BAMLH0A0HYM2`).

- [ ] **Step 3: Implement**

Replace `_CREDIT_FRED_IDS` + `fetch_credit_oas` in `src/chronos2_demo/data/fetch.py`:
```python
# Credit OAS proxy: ICE BofA OAS is licence-locked to 2023+ on FRED (no deep
# history, no ALFRED archive). BAA10Y (Moody's Baa minus 10Y Treasury, daily to
# 1986, in percent) is the deep free stand-in. US_IG_OAS = BAA10Y; US_HY_OAS is
# a fixed multiple (HY runs wider than IG). Sanctioned proxy (2026-06-05) — the
# columns keep their names + percent units but are NOT the original ICE series.
_CREDIT_PROXY_ID = "BAA10Y"
_HY_MULTIPLE = 1.7


def fetch_credit_oas(name: str, api_key: str) -> pd.Series:
    """Fetch the credit-OAS proxy (BAA10Y-based), renamed to the panel column."""
    base = fetch_fred_series(_CREDIT_PROXY_ID, api_key=api_key)
    if name == "US_IG_OAS":
        return base.rename(name)
    if name == "US_HY_OAS":
        return (base * _HY_MULTIPLE).rename(name)
    raise KeyError(name)
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/data/test_fetch.py tests/test_config.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/data/fetch.py tests/data/test_fetch.py
git commit -m "feat(data): source credit OAS from deep free BAA10Y proxy (ICE OAS licence-locked)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 45: Route MOVE to Yahoo + thread the FRED api_key

**Files:**
- Modify: `src/chronos2_demo/data/covariates.py`
- Test: `tests/data/test_covariates.py` (add a test)

`_fetch_one` maps `MOVE→"MOVE"` (not a FRED series — it doesn't exist) and hardcodes `api_key=""` (now load-bearing). Route MOVE to Yahoo `^MOVE`; keep `VIX→VIXCLS`, `WTI→DCOILWTICO` on FRED; thread `api_key` through `load_covariates`/`_fetch_one`.

- [ ] **Step 1: Write the failing test**

Append to `tests/data/test_covariates.py`:
```python
def test_fetch_one_move_uses_yahoo(monkeypatch):
    from chronos2_demo.data import covariates, fetch
    calls = {}
    monkeypatch.setattr(fetch, "fetch_yahoo_series",
                        lambda sym: _named(sym))
    monkeypatch.setattr(fetch, "fetch_fred_series",
                        lambda series_id, api_key: _named(series_id))

    def _named(name):
        import pandas as pd
        return pd.Series([1.0], index=pd.to_datetime(["2022-01-03"]), name=name)

    move = covariates._fetch_one("MOVE", api_key="k")
    vix = covariates._fetch_one("VIX", api_key="k")
    assert move.name == "MOVE"      # came from Yahoo ^MOVE, renamed
    assert vix.name == "VIX"        # came from FRED VIXCLS, renamed
```
(The existing `test_load_covariates_returns_aligned_frame` patches `_fetch_one` wholesale and stays green.)

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tests/data/test_covariates.py::test_fetch_one_move_uses_yahoo -v
```
Expected: FAIL (`_fetch_one` takes no `api_key`; MOVE routes to FRED).

- [ ] **Step 3: Implement**

Replace `src/chronos2_demo/data/covariates.py`:
```python
"""Exogenous covariates fed only to Chronos-2 (VIX / MOVE / WTI)."""
from __future__ import annotations
import pandas as pd
from chronos2_demo.data import fetch
from chronos2_demo.data.align import align_panel

_FRED_COV = {"VIX": "VIXCLS", "WTI": "DCOILWTICO"}


def _fetch_one(name: str, api_key: str) -> pd.Series:
    """Indirection so tests can patch a single function. MOVE is Yahoo-only."""
    if name == "MOVE":
        return fetch.fetch_yahoo_series("^MOVE").rename("MOVE")
    return fetch.fetch_fred_series(_FRED_COV[name], api_key=api_key).rename(name)


def load_covariates(api_key: str = "") -> pd.DataFrame:
    series = [_fetch_one(n, api_key) for n in ("VIX", "MOVE", "WTI")]
    return align_panel(series)
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tests/data/test_covariates.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/chronos2_demo/data/covariates.py tests/data/test_covariates.py
git commit -m "fix(data): fetch MOVE from Yahoo, thread FRED api_key through covariates

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 46: Wire live sources + emit `regimes.parquet` in the snapshot

**Files:**
- Modify: `scripts/snapshot_data.py`

No hermetic test (network entrypoint). Changes: equities → Yahoo (`SPX→^GSPC`, `NIKKEI225→^N225`); pass `args.fred_api_key` to `load_covariates`; emit `regimes.parquet` (one `w_stress` column — the contract `tools/lambda/load_data/handler.py` and `plot/handler.py` expect). FX already routes through the now-triangulating `fetch_ecb_fx`. (`snapshot_data.py` already imports `fetch`, `align_panel`, `load_covariates`, `config`.)

- [ ] **Step 1: Implement** (no test — verified by the live run in Task 47 / Phase 1 close)

Replace the equities loop (`scripts/snapshot_data.py:47-49`):
```python
    for idx in config.EQUITY_INDICES:
        sym = {"SPX": "^GSPC", "NIKKEI225": "^N225"}[idx]
        series.append(fetch.fetch_yahoo_series(sym).rename(idx))
```

Change the covariates call (`:58`):
```python
    cov = load_covariates(args.fred_api_key)
```

Add regimes emission after the covariates block (before `return 0`):
```python
    from chronos2_demo.data.regimes import w_stress_series
    w = w_stress_series(panel, window=20)
    w.to_frame().to_parquet(config.DATA_CURATED / "regimes.parquet")
    print(f"wrote regimes: {w.shape} → {config.DATA_CURATED / 'regimes.parquet'}")
```

- [ ] **Step 2: Confirm hermetic suite still green** (the smoke test mocks fetchers; this script isn't imported by tests)

```bash
pytest -q
```
Expected: PASS (unchanged count).

- [ ] **Step 3: Commit**

```bash
git add scripts/snapshot_data.py
git commit -m "feat(scripts): snapshot live equities via Yahoo and emit regimes.parquet

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 47: Add `seed_demo_data.py` to upload the curated panel to S3

**Files:**
- Create: `scripts/seed_demo_data.py`
- Test: `tools/tests/test_seed_demo_data.py` (moto `s3`)

The deployed Lambda tools read `panel.parquet`/`regimes.parquet` from the S3 data bucket; nothing uploads them. This script does. `main(argv=None)` (injectable for the test); `--data-bucket` required (no CfnOutput exists for the auto-named bucket); uploads the three parquets as raw bytes via `put_object`.

- [ ] **Step 1: Write the failing test**

Create `tools/tests/test_seed_demo_data.py`:
```python
import importlib.util
from pathlib import Path

import pandas as pd

_REPO = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "seed_demo_data", _REPO / "scripts" / "seed_demo_data.py")
seed = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(seed)


def test_seed_uploads_three_parquets(s3, tmp_path):
    for name in ("panel", "covariates", "regimes"):
        pd.DataFrame({"a": [1.0, 2.0]}).to_parquet(tmp_path / f"{name}.parquet")
    rc = seed.main(["--data-bucket", "test-data", "--curated-dir", str(tmp_path)])
    assert rc == 0
    for name in ("panel", "covariates", "regimes"):
        s3.head_object(Bucket="test-data", Key=f"{name}.parquet")  # raises if missing
```

- [ ] **Step 2: Run, confirm fail**

```bash
pytest tools/tests/test_seed_demo_data.py -v
```
Expected: FAIL (`scripts/seed_demo_data.py` doesn't exist).

- [ ] **Step 3: Implement**

Create `scripts/seed_demo_data.py`:
```python
"""Upload the curated demo panel (panel/covariates/regimes) to the S3 data bucket.

The deployed Lambda tools (load_data) read these from the bucket. Run after
scripts/snapshot_data.py has written data/curated/*.parquet.

Usage:
  python scripts/seed_demo_data.py --data-bucket <DataBucket-name>
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

import boto3

_FILES = ["panel.parquet", "covariates.parquet", "regimes.parquet"]


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data-bucket", required=True)
    p.add_argument("--curated-dir", default="data/curated")
    args = p.parse_args(argv)

    s3 = boto3.client("s3")
    curated = Path(args.curated_dir)
    for name in _FILES:
        body = (curated / name).read_bytes()
        s3.put_object(Bucket=args.data_bucket, Key=name, Body=body)
        print(f"uploaded s3://{args.data_bucket}/{name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run, confirm pass**

```bash
pytest tools/tests/test_seed_demo_data.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/seed_demo_data.py tools/tests/test_seed_demo_data.py
git commit -m "feat(scripts): add seed_demo_data.py to upload curated panel to S3

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 48: Forward-fill mixed-frequency series + fix the dead JPY rate

**Files:**
- Modify: `scripts/snapshot_data.py`

Discovered on the first live run (2026-06-05): the inner-join `align_panel` collapsed the live panel to **17 rows**. Two causes: (1) FRED's only free non-USD sovereign yields are **monthly** (`IRLTLT01*M156N`), which land on month-starts and almost never coincide with the daily FX/USD-rate/equity dates → inner-join near-empty; (2) the JPY 2Y/5Y series `INTGSBJPM193N` **ended 2017-05** (dead). Fix: (a) reuse the alive monthly JPY 10Y (`IRLTLT01JPM156N`) across all three JPY tenors — mirroring how EUR already reuses `IRLTLT01EZM156N`; (b) before aligning, reindex every series onto a common **business-day grid** and **forward-fill** (the conventional way to carry monthly macro on a daily panel — foreign rates become flat within each month; USD rates/FX/equities stay daily). Verified result: **2807 rows, 21 columns, 0 NaN, 1293 rows ≤ 2020-03-15** (the demo's 1260 lookback fits).

This touches only `snapshot_data.py` (the network entrypoint, no hermetic test). `align_panel` itself is **not** changed (its inner-join + dropna stays correct for already-aligned daily series and for the frozen synthetic fixture). The ffill happens in the script, before `align_panel`.

- [ ] **Step 1: Implement** (no unit test — network entrypoint; verified by the live run)

In `scripts/snapshot_data.py`, fix the dead JPY ids in `FRED_RATE_IDS`:
```python
    ("JPY", "2Y"): "IRLTLT01JPM156N", ("JPY", "5Y"): "IRLTLT01JPM156N",
    ("JPY", "10Y"): "IRLTLT01JPM156N",
```
(EUR/GBP/USD entries unchanged; this only swaps the two dead `INTGSBJPM193N` rows to the alive monthly JPY 10Y, so all three JPY tenors reuse one series exactly like EUR.)

Then replace the `panel = align_panel(series)` line with a forward-fill onto a common business-day grid:
```python
    # Series arrive at mixed frequencies (daily FX/USD-rates/equities; monthly
    # OECD foreign rates). Inner-joining raw collapses the panel, so reindex each
    # onto a common business-day grid and forward-fill (monthly macro carried
    # daily) before aligning.
    lo = max(s.dropna().index.min() for s in series)
    hi = min(s.dropna().index.max() for s in series)
    grid = pd.bdate_range(lo, hi)
    series = [s.reindex(grid).ffill() for s in series]
    panel = align_panel(series)
```

- [ ] **Step 2: Confirm hermetic suite still green**

```bash
pytest -q
```
Expected: PASS (unchanged — this script isn't imported by tests).

- [ ] **Step 3: Live run + sanity check**

```bash
python scripts/snapshot_data.py --fred-api-key "$FRED_API_KEY"
```
Expected: `wrote panel: (2807, 21)` (±a few rows as data updates), `wrote regimes: (2807,)`, panel spanning ~2015-04 → present with ≥1260 rows before 2020-03-15.

- [ ] **Step 4: Commit**

```bash
git add scripts/snapshot_data.py
git commit -m "fix(scripts): forward-fill mixed-frequency series; reuse alive JPY rate

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Plan A part-5 complete

After Task 48:
- The data layer pulls **live** data that works against today's endpoints: keyed FRED JSON, ECB triangulated USD crosses, Yahoo equities + MOVE, and a deep free `BAA10Y` credit proxy.
- Mixed-frequency series (daily + monthly OECD foreign rates) are forward-filled onto a business-day grid so the joined panel spans 2015→present (~2807 rows) instead of collapsing.
- `snapshot_data.py` emits all three curated parquets including `regimes.parquet`; `seed_demo_data.py` uploads them to the deployed data bucket.
- The hermetic suite is unchanged in spirit (only `test_fetch.py`/`test_covariates.py` mocks updated); the frozen headline regression fixture is untouched.

> _Continue with `2026-05-22-plan-b-ux-agent-part-10.md` (Stage 10 — wire what-if conditioning end-to-end through the agent + frontend)._
