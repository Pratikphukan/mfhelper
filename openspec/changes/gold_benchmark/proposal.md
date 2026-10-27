# Proposal: Domestic Gold Price Benchmark (GC=F × INR=X)

## 1. Objective

Enable `vs_benchmark` comparison for gold funds (SBI Gold Fund, ICICI Gold
ETF) by constructing the domestic gold price in INR from two yfinance series:
gold futures in USD (`GC=F`) multiplied by the USD/INR exchange rate (`INR=X`).

---

## 2. Background & Need

SBI Gold Fund (119788) and ICICI Gold ETF (113076) currently have
`index_name: ""` in `benchmarks.yaml` — their `vs_benchmark` section is
silently skipped on every run. The correct benchmark per SEBI mandate is the
**domestic price of gold in INR**, which is not directly available as a free
ticker on any public API.

The standard approach used by financial data platforms is:

```
domestic_gold_price_INR = gold_spot_USD_per_troy_oz × USD_INR_rate
```

Both components are available on Yahoo Finance:
- `GC=F` — COMEX front-month gold futures (USD/troy oz), history from 2009
- `INR=X` — USD/INR spot rate, history from 2013

This gives full coverage of both funds:
- SBI Gold Fund: inception 2013-01-02 ✓
- ICICI Gold ETF: inception 2018-11-19 ✓

---

## 3. Why Not GOLDBEES.NS

GOLDBEES.NS (Nippon India Gold ETF) is itself a gold ETF with its own
expense ratio (~0.5%/yr) and tracking error. Using one ETF as a benchmark
for another ETF is circular — the "alpha" computed would just be the
difference in expense ratios, not a meaningful signal. SEBI mandates gold
funds benchmark against the domestic gold price, not another ETF.

---

## 4. Known Limitations

- `GC=F` is the front-month **futures** price, not the spot price. It
  includes a small contango premium and rolls periodically, which can
  introduce tiny discontinuities. In practice these are negligible for
  daily NAV comparison.
- The "end of day" for `GC=F` (COMEX close, US time) and `INR=X` (RBI
  reference rate, IST) are fixed at different clock times. For daily
  NAV-level comparison this is acceptable.
- The existing `vs_benchmark.py` alignment logic anchors on fund NAV dates
  and snaps the benchmark to the nearest available date within a tolerance
  — so holiday mismatches between US and Indian markets are already handled.

---

## 5. Scope

- Add `_fetch_gold_inr()` to `mfhelper/benchmarks.py` — fetches `GC=F` and
  `INR=X` via yfinance, aligns on common dates, multiplies, returns
  `list[BenchmarkPoint]`.
- Update `fetch_benchmark_history()` to detect gold ticker syntax and route
  to `_fetch_gold_inr()`.
- Update `config/benchmarks.yaml` — set `index_name: "GOLD_INR"` (a
  synthetic ticker sentinel) for SBI Gold Fund and ICICI Gold ETF.
- Fix hardcoded `"data_source": "niftyindices.com"` in `vs_benchmark.py`
  line 373 — should read from `BenchmarkHistory.data_source`.

---

## 6. Exclusions

- No change to `vs_benchmark.py` computation logic.
- No change to callers (`returns_main.py`, `plot_main.py`).
- No currency conversion for international funds (out of scope).
