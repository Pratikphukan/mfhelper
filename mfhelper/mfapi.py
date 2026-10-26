"""mfapi.in client.

Used as a secondary NAV source: provides per-scheme NAV history that
AMFI's bulk NAVAll.txt doesn't expose. We use it for three purposes in
a single round-trip per fund per run:

1. **Fallback for the latest NAV** -- when a configured scheme code is
   missing from AMFI's daily file (which happens during partial publishes
   or AMC reporting delays). The latest entry in the returned history is
   used in place of the missing AMFI record.

2. **52-week-high computation** -- the full history lets ``mfhelper.metrics``
   find the highest NAV in the trailing 365-day window.

3. **200-day SMA and 14-day RSI** -- the same history feeds the rolling
   moving-average and momentum oscillators.

Endpoint: ``https://api.mfapi.in/mf/{scheme_code}``

Response shape:

    {
      "meta": {"scheme_name": "...", ...},
      "data": [{"date": "DD-MM-YYYY", "nav": "45.65960"}, ...],  # newest first
      "status": "SUCCESS"
    }

Invalid / unknown scheme codes still return HTTP 200 with an empty
``data`` list.

The HTTP request uses a separate connect / read timeout (mfapi.in can
take a moment to establish TLS during peak hours but streams the JSON
quickly once connected) and retries with exponential backoff on transient
failures (timeouts, connection errors, 5xx). 4xx responses are not retried.

Local cache
-----------
Full history responses are cached to ``data/mfapi_cache/{code}.json`` with
an 18-hour TTL. Within a single GitHub Actions run (where ``main.py`` and
``returns_main.py`` execute back-to-back), the cache is always fresh so
``returns_main.py`` never hits the API again. Between daily runs (~24 hours
apart) the cache is always stale, ensuring fresh data every day.

The cache always stores the **full** history regardless of the ``limit``
argument. Callers that pass ``limit=365`` get the first 365 entries sliced
from the cached list, so even a limited fetch populates the full cache for
subsequent unlimited fetches.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import logging
import time
from pathlib import Path

import requests

MFAPI_HISTORY_URL = "https://api.mfapi.in/mf/{code}"
HTTP_CONNECT_TIMEOUT_SECONDS = 30
HTTP_READ_TIMEOUT_SECONDS = 45
HTTP_TIMEOUT: tuple[int, int] = (HTTP_CONNECT_TIMEOUT_SECONDS, HTTP_READ_TIMEOUT_SECONDS)
RETRY_ATTEMPTS = 5
RETRY_BACKOFF_SECONDS = 2.5

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = _PROJECT_ROOT / "data" / "mfapi_cache"
CACHE_TTL_HOURS = 18

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class NavHistoryPoint:
    nav_date: date
    nav: float


@dataclass(frozen=True)
class MfapiResult:
    scheme_name: str
    history: list[NavHistoryPoint]  # newest first

    @property
    def latest(self) -> NavHistoryPoint:
        return self.history[0]


def _fetch_payload(
    url: str,
    *,
    timeout: tuple[int, int],
    attempts: int,
    backoff_seconds: float,
    log_subject: str,
) -> dict | None:
    """GET ``url`` with retries on transient failures. Returns parsed JSON or None."""
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except (requests.ConnectionError, requests.Timeout) as exc:
            if attempt < attempts:
                sleep_s = backoff_seconds * (2 ** (attempt - 1))
                log.info(
                    "mfapi.in attempt %d/%d failed for %s (%s); retrying in %.1fs",
                    attempt,
                    attempts,
                    log_subject,
                    type(exc).__name__,
                    sleep_s,
                )
                time.sleep(sleep_s)
                continue
            log.warning(
                "mfapi.in fetch failed for %s after %d attempt(s): %s",
                log_subject,
                attempts,
                exc,
            )
            return None
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status is not None and 500 <= status < 600 and attempt < attempts:
                sleep_s = backoff_seconds * (2 ** (attempt - 1))
                log.info(
                    "mfapi.in HTTP %d for %s (attempt %d/%d); retrying in %.1fs",
                    status,
                    log_subject,
                    attempt,
                    attempts,
                    sleep_s,
                )
                time.sleep(sleep_s)
                continue
            log.warning(
                "mfapi.in fetch failed for %s: HTTP %s",
                log_subject,
                status if status is not None else "?",
            )
            return None
        except ValueError as exc:
            log.warning("mfapi.in returned non-JSON for %s: %s", log_subject, exc)
            return None
    return None


def _parse_history(raw_data: list[dict]) -> list[NavHistoryPoint]:
    """Parse a list of raw mfapi.in data entries into ``NavHistoryPoint`` objects."""
    history: list[NavHistoryPoint] = []
    for entry in raw_data:
        date_str = str(entry.get("date", "")).strip()
        nav_str = str(entry.get("nav", "")).strip()
        try:
            nav = float(nav_str)
            nav_date = datetime.strptime(date_str, "%d-%m-%Y").date()
        except ValueError:
            continue
        history.append(NavHistoryPoint(nav_date=nav_date, nav=nav))
    return history


def _read_cache(code: str) -> MfapiResult | None:
    """Return a cached ``MfapiResult`` if one exists and is within TTL, else None."""
    cache_path = CACHE_DIR / f"{code}.json"
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(payload["fetched_at"])
        age_hours = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600
        if age_hours > CACHE_TTL_HOURS:
            return None
        history = _parse_history(payload["data"])
        if not history:
            return None
        return MfapiResult(scheme_name=payload["scheme_name"], history=history)
    except Exception as exc:
        log.warning("mfapi cache read failed for %s (%s); will fetch fresh", code, exc)
        return None


def _write_cache(code: str, scheme_name: str, raw_data: list[dict]) -> None:
    """Atomically write the full history response to the cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "scheme_name": scheme_name,
        "data": raw_data,
    }
    cache_path = CACHE_DIR / f"{code}.json"
    tmp_path = cache_path.with_suffix(".tmp")
    try:
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        tmp_path.replace(cache_path)
    except Exception as exc:
        log.warning("mfapi cache write failed for %s (%s); continuing without cache", code, exc)


def fetch_history(
    code: str,
    *,
    limit: int | None = None,
    timeout: tuple[int, int] = HTTP_TIMEOUT,
    attempts: int = RETRY_ATTEMPTS,
    backoff_seconds: float = RETRY_BACKOFF_SECONDS,
) -> MfapiResult | None:
    """Return mfapi.in's NAV history for ``code``, optionally sliced, or ``None`` on any failure.

    Full history is cached to ``data/mfapi_cache/{code}.json`` for
    ``CACHE_TTL_HOURS`` hours. A cache hit skips the API call entirely.
    The ``limit`` argument slices the result **after** reading from cache,
    so even a limited fetch populates the full cache for subsequent calls.

    Callers should treat ``None`` as "not available from this source" and
    react accordingly (typically: skip the metric and log).
    """
    # Try cache first.
    cached = _read_cache(code)
    if cached is not None:
        log.info("mfapi cache hit for %s (%d points)", code, len(cached.history))
        if limit is not None:
            return MfapiResult(scheme_name=cached.scheme_name, history=cached.history[:limit])
        return cached
    log.info("mfapi cache miss for %s; fetching from API", code)

    url = MFAPI_HISTORY_URL.format(code=code)
    payload = _fetch_payload(
        url,
        timeout=timeout,
        attempts=attempts,
        backoff_seconds=backoff_seconds,
        log_subject=code,
    )
    if payload is None:
        return None

    raw_data = payload.get("data") or []
    if not raw_data:
        return None

    meta = payload.get("meta") or {}
    scheme_name = str(meta.get("scheme_name") or code).strip()

    # Cache the full response before applying limit.
    _write_cache(code, scheme_name, raw_data)

    history = _parse_history(raw_data)
    if not history:
        return None

    if limit is not None:
        history = history[:limit]

    return MfapiResult(scheme_name=scheme_name, history=history)
