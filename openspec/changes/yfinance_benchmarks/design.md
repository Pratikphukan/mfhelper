# Design: Replace niftyindices.com with yfinance for Benchmark Data

## 1. Data Flow (unchanged externally)

```
returns_main.py / plot_main.py
        │
        ▼
fetch_benchmark_history(name="^CRSLDX", variant="PR", cache_dir=...)
        │
        ├── Cache HIT (< 18h old) ──► return BenchmarkHistory from disk
        │
        └── Cache MISS
                │
                ▼
        yf.download("^CRSLDX", start="2009-01-01")   ← replaces POST to niftyindices.com
                │
                ▼
        Parse DataFrame → list[BenchmarkPoint]
                │
                ▼
        Write to data/benchmark_history/^CRSLDX_PR.json (atomic)
                │
                ▼
        return BenchmarkHistory
```

---

## 2. `config/benchmarks.yaml` Changes

The `index_name` field is repurposed from niftyindices.com dropdown spelling
to Yahoo Finance ticker. The `variant` field is unchanged.

```yaml
# Before
- code: "120492"
  index_name: "NIFTY 500"
  variant: "PR"

# After
- code: "120492"
  index_name: "^CRSLDX"       # Yahoo Finance ticker for NIFTY 500
  variant: "PR"
```

Full mapping:

| Fund | Old index_name | New index_name (Yahoo ticker) |
|---|---|---|
| JM Flexicap (120492) | `NIFTY 500` | `^CRSLDX` |
| Motilal Oswal Midcap (127042) | `NIFTY MIDCAP 150` | `^NSEMDCP50` |
| quant ELSS (120847) | `NIFTY 500` | `^CRSLDX` |
| Mirae ELSS (135781) | `NIFTY 500` | `^CRSLDX` |
| SBI Large & Midcap (119721) | `NIFTY 200` | `^CNX200` |

Funds with `index_name: ""` remain unchanged (still skipped).

---

## 3. `mfhelper/benchmarks.py` Rewrite

### 3.1 Remove
- `NIFTYINDICES_URL`, `HTTP_HEADERS`, `HTTP_TIMEOUT` constants
- `_fetch_raw()` function (the POST logic)
- `_format_date_for_endpoint()`, `_parse_endpoint_date()` helpers

### 3.2 Add
- `import yfinance as yf`
- `_fetch_yfinance(ticker, start, end)` function:

```python
def _fetch_yfinance(
    ticker: str,
    *,
    start: date,
    end: date,
) -> list[BenchmarkPoint] | None:
    """Fetch daily closes from Yahoo Finance for ``ticker``."""
    try:
        df = yf.download(
            ticker,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),  # yfinance end is exclusive
            progress=False,
            auto_adjust=True,
        )
    except Exception as exc:
        log.warning("yfinance download failed for %r: %s", ticker, exc)
        return None

    if df is None or df.empty:
        log.warning("yfinance returned empty data for %r", ticker)
        return None

    points: list[BenchmarkPoint] = []
    for ts, row in df.iterrows():
        try:
            close = float(row["Close"])
            points.append(BenchmarkPoint(date=ts.date(), close=close))
        except (KeyError, ValueError):
            continue

    points.sort(key=lambda p: p.date)
    return points if points else None
```

### 3.2 Keep unchanged
- `BenchmarkPoint`, `BenchmarkHistory` dataclasses
- `_sanitize_for_filename()`, `_cache_path()`
- `_load_cache()`, `_save_cache()`, `_is_fresh()`
- `fetch_benchmark_history()` public interface — only swap `_fetch_raw()` call
  for `_fetch_yfinance()` call inside it

### 3.3 `fetch_benchmark_history()` change (minimal)

```python
# Before
rows = _fetch_raw(name, start=start, end=end)
if rows is None or not rows:
    ...
history = _parse_rows(name, rows)

# After
history = _fetch_yfinance(name, start=start, end=end)
if history is None:
    ...
# No _parse_rows needed — yfinance output is already parsed into BenchmarkPoints
```

---

## 4. `requirements.txt` Change

```
yfinance>=0.2,<1
```

---

## 5. GitHub Actions Workflow Change

Add `data/benchmark_history/` to the Actions cache so a locally-warmed
cache survives across CI runs:

```yaml
- name: Restore Daily NAV State Cache
  uses: actions/cache/restore@v4
  with:
    path: |
      data/last_nav.json
      data/sheet_columns.json
      data/combined_portfolio_allocation.json
      data/mfapi_cache/
      data/benchmark_history/     # <-- add this

- name: Save Daily NAV State Cache
  uses: actions/cache/save@v4
  with:
    path: |
      data/last_nav.json
      data/sheet_columns.json
      data/combined_portfolio_allocation.json
      data/mfapi_cache/
      data/benchmark_history/     # <-- add this
```

Since yfinance now works from CI, the cache will be populated on the first
run and reused for subsequent runs within 18 hours (i.e. within the same day
if triggered multiple times).

---

## 6. Cache File Naming

The cache file is named `{sanitized_ticker}_{variant}.json`. Since tickers
now contain `^`, `_sanitize_for_filename()` already handles this:

```
"^CRSLDX"  →  "CRSLDX_PR.json"
"^CNX200"   →  "CNX200_PR.json"
"^NSEMDCP50" →  "NSEMDCP50_PR.json"
```

Existing cache files (named after old niftyindices.com index names like
`NIFTY_500_PR.json`) will simply be ignored — the new ticker-based filenames
won't match them. They can be deleted manually.
