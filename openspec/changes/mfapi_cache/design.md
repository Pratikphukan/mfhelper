# Design: mfapi.in Local History Cache

## 1. Data Flow

```
GitHub Actions run
│
├── main.py
│   └── mfapi_fetch_history(code, limit=365)
│       ├── Cache MISS (yesterday's cache is >18h old) → fetch from mfapi.in
│       └── Write full response to data/mfapi_cache/{code}.json
│
└── returns_main.py
    └── mfapi_fetch_history(code, limit=None)
        ├── Cache HIT (written minutes ago by main.py) → read from disk
        └── Skip API call entirely
```

---

## 2. Cache File Format

`data/mfapi_cache/{code}.json`

```json
{
  "fetched_at": "2026-10-26T10:32:05+05:30",
  "scheme_name": "JM Flexicap Fund (Direct) - Growth Option",
  "data": [
    {"date": "2026-10-24", "nav": 112.2117},
    {"date": "2026-10-23", "nav": 110.2021},
    ...
  ]
}
```

- `fetched_at`: ISO-8601 timestamp with timezone. Used to check TTL.
- `scheme_name`: Stored alongside data so callers get the full `MfapiResult`.
- `data`: The raw history list as returned by mfapi.in (newest first).

---

## 3. Cache Logic in `mfhelper/mfapi.py`

Introduce a `CACHE_DIR` constant and a `CACHE_TTL_HOURS = 18` constant.

Modify `fetch_history()` to:

1. Compute the cache file path: `CACHE_DIR / f"{code}.json"`.
2. If the file exists and `fetched_at` is within TTL → deserialise and return
   a `MfapiResult` from the cached data. Log a single `cache hit` line.
3. Otherwise → fetch from mfapi.in as today, write the response atomically
   (tmp file → rename, same pattern as `state.py`) to the cache file, then
   return the result. Log a single `cache miss` line.

The `limit` parameter still applies **after** reading from cache — i.e. the
cache always stores the full history, and callers that pass `limit=365` get
the first 365 entries sliced from the cached list. This means `main.py`'s
limited fetch also populates the full cache for `returns_main.py`.

**Atomic write pattern** (same as `state.py`):
```python
tmp = cache_path.with_suffix(".tmp")
tmp.write_text(json.dumps(payload), encoding="utf-8")
tmp.replace(cache_path)
```

---

## 4. GitHub Actions Workflow Changes

Add `data/mfapi_cache/` to both the restore and save steps in
`.github/workflows/daily_nav.yml`:

```yaml
- name: Restore Daily NAV State Cache
  uses: actions/cache/restore@v4
  with:
    path: |
      data/last_nav.json
      data/sheet_columns.json
      data/combined_portfolio_allocation.json
      data/mfapi_cache/          # <-- add this
    key: daily-nav-state-${{ github.run_id }}-${{ github.run_number }}
    restore-keys: |
      daily-nav-state-

- name: Save Daily NAV State Cache
  uses: actions/cache/save@v4
  with:
    path: |
      data/last_nav.json
      data/sheet_columns.json
      data/combined_portfolio_allocation.json
      data/mfapi_cache/          # <-- add this
    key: daily-nav-state-${{ github.run_id }}-${{ github.run_number }}
```

---

## 5. `.gitignore` Change

```
data/mfapi_cache/
```

---

## 6. TTL Behaviour Summary

| Scenario | Cache state at run start | Behaviour |
|---|---|---|
| GitHub Actions daily run | Stale (>18h, yesterday's) | `main.py` fetches fresh, populates cache. `returns_main.py` hits cache. |
| Manual re-trigger same day | Fresh (<18h) | Both `main.py` and `returns_main.py` hit cache. No API calls. |
| Local dev, repeated runs | Fresh (<18h) | Same as above — fast repeated runs. |
| Local dev, next day | Stale (>18h) | Fresh fetch, cache repopulated. |
