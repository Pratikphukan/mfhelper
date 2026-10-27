# Design: Domestic Gold Price Benchmark (GC=F × INR=X)

## 1. Data Flow

```
fetch_benchmark_history("GOLD_INR", ...)
        │
        ├── Cache HIT (< 18h) ──► return BenchmarkHistory from disk
        │
        └── Cache MISS
                │
                ├── yf.download("GC=F")   → gold_usd (USD/troy oz)
                ├── yf.download("INR=X")  → usd_inr  (INR per USD)
                │
                ├── Align on common dates (inner join)
                ├── Forward-fill residual gaps (max 3 days)
                ├── gold_inr = gold_usd × usd_inr
                │
                ▼
        list[BenchmarkPoint] → BenchmarkHistory
                │
                ▼
        Write to data/benchmark_history/GOLD_INR_PR.json (atomic)
```

---

## 2. Synthetic Ticker: `"GOLD_INR"`

A special sentinel string `"GOLD_INR"` is used as the `index_name` in
`benchmarks.yaml`. `fetch_benchmark_history()` detects this and routes to
`_fetch_gold_inr()` instead of `_fetch_yfinance()`.

This keeps the public interface identical — callers pass `name="GOLD_INR"` and
get back a `BenchmarkHistory` object just like any other benchmark.

---

## 3. `_fetch_gold_inr()` Implementation

```python
GOLD_FUTURES_TICKER = "GC=F"
USDINR_TICKER = "INR=X"
GOLD_INR_SENTINEL = "GOLD_INR"
MAX_FFILL_DAYS = 3

def _fetch_gold_inr(*, start: date, end: date) -> list[BenchmarkPoint] | None:
    df_gold = yf.download(GOLD_FUTURES_TICKER, start=..., end=..., progress=False, auto_adjust=True)
    df_inr  = yf.download(USDINR_TICKER,       start=..., end=..., progress=False, auto_adjust=True)

    if df_gold.empty or df_inr.empty:
        return None

    gold = df_gold["Close"].squeeze().rename("gold_usd")
    inr  = df_inr["Close"].squeeze().rename("usd_inr")

    # Outer join → forward-fill gaps up to MAX_FFILL_DAYS → drop remaining NaN
    combined = pd.concat([gold, inr], axis=1, sort=True)
    combined = combined.ffill(limit=MAX_FFILL_DAYS).dropna()

    points = [
        BenchmarkPoint(date=ts.date(), close=float(row["gold_usd"] * row["usd_inr"]))
        for ts, row in combined.iterrows()
    ]
    points.sort(key=lambda p: p.date)
    return points or None
```

Key choices:
- **Outer join** — keeps dates present in either series; forward-fill fills
  gaps up to `MAX_FFILL_DAYS` (3 days covers any long weekend); `dropna()`
  drops any remaining gaps at the very start of history.
- **`MAX_FFILL_DAYS = 3`** — conservative limit so we don't propagate stale
  gold prices across extended market closures.
- **`auto_adjust=True`** — handles any corporate action adjustments in the
  futures series (rare but safe).

---

## 4. `fetch_benchmark_history()` Routing Change

```python
def fetch_benchmark_history(name, *, variant="PR", cache_dir, start, end, force_refresh):
    cache_path = _cache_path(cache_dir, name, variant)

    # Cache check (unchanged)
    if not force_refresh:
        cached = _load_cache(cache_path)
        if cached and _is_fresh(cached):
            return cached

    # Route to gold constructor or standard yfinance fetch
    if name == GOLD_INR_SENTINEL:
        history = _fetch_gold_inr(start=start, end=end)
        data_source = "yahoo_finance:GC=F×INR=X"
    else:
        history = _fetch_yfinance(name, start=start, end=end)
        data_source = "yahoo_finance"

    # Stale cache fallback + save (unchanged)
    ...
```

---

## 5. `config/benchmarks.yaml` Changes

```yaml
- code: "119788"
  fund_name: "SBI GOLD FUND - DIRECT PLAN - GROWTH"
  index_name: "GOLD_INR"
  variant: "PR"
  note: "Domestic gold price in INR, constructed as GC=F (COMEX gold
    futures, USD/troy oz) × INR=X (USD/INR spot rate) via yfinance.
    GC=F is the front-month futures price — includes a small contango
    premium vs spot, and rolls periodically. For daily NAV comparison
    the difference is negligible. This is the standard SEBI-mandated
    benchmark for gold funds."

- code: "113076"
  fund_name: "ICICI Prudential Gold ETF"
  index_name: "GOLD_INR"
  variant: "PR"
  note: "Same construction as SBI Gold Fund above (GC=F × INR=X)."
```

---

## 6. Fix `data_source` Hardcode in `vs_benchmark.py`

Line 373 currently hardcodes `"data_source": "niftyindices.com"`. Change to
read from the `BenchmarkHistory` object passed in:

```python
# Before (line 373)
"data_source": "niftyindices.com",

# After
"data_source": benchmark_history_obj.data_source,
```

This requires passing the `BenchmarkHistory` object into `compute_vs_benchmark()`
or adding `data_source` as a parameter. The cleanest fix is to add
`data_source: str` as a parameter defaulting to `"yahoo_finance"`.

---

## 7. Cache File

```
data/benchmark_history/GOLD_INR_PR.json
```

Same format as other benchmark caches. The `name` field stores `"GOLD_INR"`,
`data_source` stores `"yahoo_finance:GC=F×INR=X"`.
