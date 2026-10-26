# Tasks: Replace niftyindices.com with yfinance for Benchmark Data

---

## Phase 1: Dependencies

* [ ] Add `yfinance>=0.2,<1` to `requirements.txt`.

## Phase 2: Rewrite `mfhelper/benchmarks.py`

* [ ] Remove `NIFTYINDICES_URL`, `HTTP_HEADERS`, `HTTP_TIMEOUT` constants.
* [ ] Remove `_fetch_raw()`, `_format_date_for_endpoint()`,
      `_parse_endpoint_date()`, `_parse_rows()` functions.
* [ ] Add `_fetch_yfinance(ticker, *, start, end)` function using
      `yf.download()` — returns `list[BenchmarkPoint] | None`.
* [ ] Update `fetch_benchmark_history()` to call `_fetch_yfinance()` instead
      of `_fetch_raw()` + `_parse_rows()`.
* [ ] Update module docstring to reflect yfinance as the data source.

## Phase 3: Update `config/benchmarks.yaml`

* [ ] Change `index_name` for all 5 active benchmarks to Yahoo Finance tickers:
  - `NIFTY 500` → `^CRSLDX`
  - `NIFTY MIDCAP 150` → `^NSEMDCP50`
  - `NIFTY 200` → `^CNX200`
* [ ] Update the schema comment at the top to describe `index_name` as a
      Yahoo Finance ticker.
* [ ] Update `note` fields to reference yfinance/Yahoo Finance instead of
      niftyindices.com.

## Phase 4: GitHub Actions Workflow

* [ ] Add `data/benchmark_history/` to the `path:` block in the
      `Restore Daily NAV State Cache` step.
* [ ] Add `data/benchmark_history/` to the `path:` block in the
      `Save Daily NAV State Cache` step.

## Phase 5: Update `.gitignore`

* [ ] Confirm `data/benchmark_history/` is already in `.gitignore`
      (it should be — verify and add if missing).

## Phase 6: Verification

* [ ] Run `returns_main.py --code 120492` locally — confirm `vs_benchmark`
      section appears in `data/fund_returns/120492.json`.
* [ ] Check `data/benchmark_history/CRSLDX_PR.json` is created.
* [ ] Run `returns_main.py --code 120492` again immediately — confirm
      `Using cached benchmark` log line (cache hit).
* [ ] Trigger a manual GitHub Actions run — confirm no benchmark fetch
      failures in the `returns_main.py` step logs.
* [ ] Confirm `vs_benchmark` sections are populated in the generated
      `dashboard.html`.
