# Proposal: mfapi.in Local History Cache

## 1. Objective

Introduce a local JSON cache for mfapi.in NAV history fetches so that multiple
scripts within the same GitHub Actions run (or the same local session) share a
single HTTP fetch per fund instead of making redundant API calls.

---

## 2. Background & Need

The daily GitHub Actions workflow runs four scripts in sequence:

```
main.py            → mfapi_fetch_history(code, limit=365)   per fund
returns_main.py    → mfapi_fetch_history(code, limit=None)  per fund (full history)
portfolio_map_main.py → no mfapi calls
dashboard_main.py  → no mfapi calls
```

`main.py` fetches the last 365 NAV data points per fund for computing 52W high,
200D SMA, and RSI. `returns_main.py` fetches the **full history** (up to 15 years
of daily NAVs) per fund for CAGR, rolling returns, max drawdown, and SIP XIRR.

Within a single run both scripts independently hit the mfapi.in API for the same
funds. Since the workflow steps run back-to-back (within minutes of each other),
the data returned is identical — the second fetch is entirely wasted.

For 13 funds with 10+ years of history each, the full-history fetch in
`returns_main.py` alone accounts for the majority of the workflow's network time
and API load.

---

## 3. Scope

- Cache full mfapi.in history responses to `data/mfapi_cache/{code}.json`.
- Cache TTL: **18 hours** (same as `benchmarks.py`). Within a single GitHub
  Actions run (~5 minutes), the cache is always fresh. Between daily runs
  (~24 hours apart), the cache is always stale — so fresh data is always fetched
  at the start of each day's run.
- `main.py` always fetches fresh (cache is stale from yesterday's run). Its fetch
  populates the cache. `returns_main.py` reads from the cache instead of hitting
  the API again.
- Add `data/mfapi_cache/` to the GitHub Actions cache (`actions/cache`) so it
  persists within the same run across steps. Between runs it will be stale and
  re-fetched anyway.
- Add `data/mfapi_cache/` to `.gitignore`.

---

## 4. Exclusions

- No in-memory caching (scripts are separate processes).
- No cross-day cache reuse (TTL ensures fresh data every run).
- No changes to the API call interface — the cache is transparent to callers.
