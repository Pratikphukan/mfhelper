# Proposal: Replace niftyindices.com with yfinance for Benchmark Data

## 1. Objective

Replace the niftyindices.com benchmark fetcher with Yahoo Finance (`yfinance`)
so that benchmark vs-fund comparisons work reliably in GitHub Actions CI,
where niftyindices.com actively blocks datacenter IP ranges (Azure/GitHub
Actions runners).

---

## 2. Background & Need

`mfhelper/benchmarks.py` fetches NIFTY index historical data by POSTing to
niftyindices.com's internal JSON endpoint. This works locally (residential
IP), but GitHub Actions runs on Azure (`westus3`), which niftyindices.com
blocks with bot detection — returning an HTML CAPTCHA/challenge page instead
of JSON. All 3 retry attempts fail for every benchmark-mapped fund, and since
there is no warm cache in CI, the `vs_benchmark` section is silently skipped
for every fund on every CI run.

From the GitHub Actions logs:
```
WARNING niftyindices.com returned non-JSON/HTML on attempt 1/3 for 'NIFTY 500'
WARNING niftyindices.com returned non-JSON/HTML on attempt 2/3 for 'NIFTY 500'
WARNING niftyindices.com returned non-JSON/HTML on attempt 3/3 for 'NIFTY 500'
ERROR   No live data and no cache available for 'NIFTY 500'
WARNING Benchmark fetch failed for 120492 (index 'NIFTY 500'); skipping vs_benchmark section
```

This affects all 5 benchmark-mapped equity funds every daily run.

---

## 3. Why yfinance

`yfinance` is a well-maintained Python library that wraps Yahoo Finance's
public API. Key properties:

- **Works from GitHub Actions** — Yahoo Finance does not block datacenter IPs.
- **Same data quality** — PR (Price Return) daily closes, same as
  niftyindices.com. No regression in data quality.
- **Full history** — all 4 required NIFTY indices have data back to 2009,
  matching niftyindices.com's depth.
- **No auth, no API key, free.**
- **Actively maintained** — unlike scraping a private endpoint.

Yahoo Finance tickers for required indices (verified locally):

| Index | Yahoo Ticker | Points | History |
|---|---|---|---|
| NIFTY 50 | `^NSEI` | 4370 | 2009→today |
| NIFTY 200 | `^CNX200` | 4384 | 2009→today |
| NIFTY 500 | `^CRSLDX` | 4379 | 2009→today |
| NIFTY MIDCAP 150 | `^NSEMDCP50` | 4343 | 2009→today |

---

## 4. What Does NOT Change

- **Data type:** still PR (Price Return). The ~1–1.5%/yr TRI gap vs fund
  returns is unchanged and already documented in `benchmarks.yaml` notes and
  the per-fund JSON `vs_benchmark.data_quality.note`.
- **Cache behaviour:** same 18-hour TTL, same atomic write pattern, same
  `data/benchmark_history/` directory.
- **`benchmarks.yaml` schema:** `index_name` field is repurposed to hold the
  Yahoo Finance ticker (e.g. `^CRSLDX`) instead of the niftyindices.com
  dropdown name. The `variant` field stays as-is.
- **Caller interface:** `fetch_benchmark_history()` signature is unchanged.
  All callers (`returns_main.py`, `plot_main.py`) require no changes.

---

## 5. Scope

- Rewrite `mfhelper/benchmarks.py` to use `yfinance` instead of the
  niftyindices.com POST endpoint.
- Update `config/benchmarks.yaml` — change `index_name` values to Yahoo
  Finance tickers, update comments to reflect the new data source.
- Add `yfinance` to `requirements.txt`.
- Add `data/benchmark_history/` to the GitHub Actions cache so the warm
  cache persists across daily runs (avoiding a fetch on every run).
- Update tests to mock `yfinance` instead of `requests`.

---

## 6. Exclusions

- No change to the PR-vs-TRI gap — both sources are PR only.
- International fund benchmarks (Franklin US, Axis Global) and gold/debt
  fund benchmarks remain `index_name: ""` (skipped) for now — those require
  currency conversion or different data sources and are out of scope.
- No change to `vs_benchmark.py` or any caller.
