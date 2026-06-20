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
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import logging
import time

import requests

MFAPI_HISTORY_URL = "https://api.mfapi.in/mf/{code}"
HTTP_CONNECT_TIMEOUT_SECONDS = 20
HTTP_READ_TIMEOUT_SECONDS = 30
HTTP_TIMEOUT: tuple[int, int] = (HTTP_CONNECT_TIMEOUT_SECONDS, HTTP_READ_TIMEOUT_SECONDS)
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2.0

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


def fetch_history(
    code: str,
    *,
    timeout: tuple[int, int] = HTTP_TIMEOUT,
    attempts: int = RETRY_ATTEMPTS,
    backoff_seconds: float = RETRY_BACKOFF_SECONDS,
) -> MfapiResult | None:
    """Return mfapi.in's full NAV history for ``code``, or ``None`` on any failure.

    Callers should treat ``None`` as "not available from this source" and
    react accordingly (typically: skip the metric and log).
    """
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

    if not history:
        return None

    meta = payload.get("meta") or {}
    scheme_name = str(meta.get("scheme_name") or code).strip()

    return MfapiResult(scheme_name=scheme_name, history=history)
