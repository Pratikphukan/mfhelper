# Tasks: Domestic Gold Price Benchmark (GC=F × INR=X)

---

## Phase 1: `mfhelper/benchmarks.py`

* [ ] Add constants: `GOLD_FUTURES_TICKER = "GC=F"`, `USDINR_TICKER = "INR=X"`,
      `GOLD_INR_SENTINEL = "GOLD_INR"`, `MAX_FFILL_DAYS = 3`.
* [ ] Add `import pandas as pd`.
* [ ] Implement `_fetch_gold_inr(*, start, end)` — fetches both tickers,
      outer-joins on date, forward-fills up to `MAX_FFILL_DAYS`, multiplies,
      returns `list[BenchmarkPoint] | None`.
* [ ] Update `fetch_benchmark_history()` — detect `name == GOLD_INR_SENTINEL`
      and route to `_fetch_gold_inr()` instead of `_fetch_yfinance()`.
* [ ] Set `data_source = "yahoo_finance:GC=F×INR=X"` for gold construction.

## Phase 2: `config/benchmarks.yaml`

* [ ] Set `index_name: "GOLD_INR"` for SBI Gold Fund (119788).
* [ ] Set `index_name: "GOLD_INR"` for ICICI Gold ETF (113076).
* [ ] Update `note` fields to describe the GC=F × INR=X construction.

## Phase 3: Fix `data_source` hardcode in `vs_benchmark.py`

* [ ] Add `data_source: str = "yahoo_finance"` parameter to
      `compute_vs_benchmark()`.
* [ ] Replace hardcoded `"data_source": "niftyindices.com"` at line 373
      with the `data_source` parameter value.
* [ ] Update callers in `returns_main.py` and `plot_main.py` to pass
      `data_source=benchmark_hist.data_source`.

## Phase 4: Verification

* [ ] Run locally: `returns_main.py --code 119788` — confirm `vs_benchmark`
      section appears in `data/fund_returns/119788.json`.
* [ ] Run locally: `returns_main.py --code 113076` — confirm same for
      ICICI Gold ETF.
* [ ] Check `data/benchmark_history/GOLD_INR_PR.json` is created with
      reasonable values (~₹3.5-4L per troy oz today).
* [ ] Run again immediately — confirm cache hit log line.
* [ ] Trigger manual GitHub Actions run — confirm no benchmark failures
      for gold funds in CI logs.
