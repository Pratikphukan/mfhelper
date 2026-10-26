# Tasks: mfapi.in Local History Cache

---

## Phase 1: Cache Implementation (`mfhelper/mfapi.py`)

* [ ] Add `CACHE_DIR = PROJECT_ROOT / "data" / "mfapi_cache"` and
      `CACHE_TTL_HOURS = 18` constants.
* [ ] On `fetch_history()` call: check for a valid cached file. If fresh
      (within TTL), deserialise and return a `MfapiResult` from it.
* [ ] On cache miss: fetch from mfapi.in as before, then write the full
      response atomically to `CACHE_DIR / f"{code}.json"` before returning.
* [ ] Apply `limit` slicing **after** reading from cache so the full history
      is always stored regardless of the `limit` argument.
* [ ] Log `cache hit` / `cache miss` at `INFO` level for observability.

## Phase 2: Housekeeping

* [ ] Add `data/mfapi_cache/` to `.gitignore`.
* [ ] Ensure `CACHE_DIR.mkdir(parents=True, exist_ok=True)` is called before
      any cache write (same pattern as other data dirs).

## Phase 3: GitHub Actions Workflow (`daily_nav.yml`)

* [ ] Add `data/mfapi_cache/` to the `path:` block in the
      `Restore Daily NAV State Cache` step.
* [ ] Add `data/mfapi_cache/` to the `path:` block in the
      `Save Daily NAV State Cache` step.

## Phase 4: Verification

* [ ] Run `main.py` locally — confirm `cache miss` logs and files written to
      `data/mfapi_cache/`.
* [ ] Run `returns_main.py` immediately after — confirm `cache hit` logs and
      no API calls made.
* [ ] Run again after manually setting `fetched_at` to >18h ago — confirm
      cache miss and fresh fetch.
* [ ] Trigger a manual GitHub Actions run and confirm both steps share the
      cache (check logs for `cache hit` in the `returns_main.py` step).
