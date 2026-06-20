"""niftyindices.com benchmark history fetcher with local caching.

Fetches historical NIFTY index data via niftyindices.com's public
historical-data JSON endpoint (the same one that powers their
"Reports -> Historical Data" tool). We use this for fund-vs-benchmark
comparison: each fund's :mod:`mfhelper.returns_calc` rolling-window
metrics get a benchmark counterpart so we can compute alpha
(active return), beat-rate, and information-ratio distributions.

Why niftyindices.com:
- Authoritative source (NSE Indices Ltd publishes these series).
- Free, no API key, no signup.
- Daily granularity; full history back to ~Jan 2010 for major indices.

What we get vs. what we'd ideally want:
- The endpoint exposes Price Return (PR) data cleanly. The Total Return
  Index (TRI) variant -- which is what every AMC factsheet uses for
  fund-vs-benchmark comparison -- is gated behind a UI tab that doesn't
  expose a stable public JSON endpoint without a headless browser.
- We mark the variant we actually fetched in the cache file and surface
  it into per-fund JSON, so the dividend-yield gap (~1-1.5%/yr) between
  PR and TRI is auditable.

Local caching:
- Each index is cached at ``data/benchmark_history/<sanitized_name>.json``.
- A fetch is reused for ``CACHE_FRESHNESS_HOURS`` hours; older caches
  are refreshed. This keeps repeat runs fast (hundreds of ms) without
  serving stale data when you actually want fresh numbers.
- The cache writer is atomic (.tmp + rename), same pattern as
  ``mfhelper.returns_writer``.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

NIFTYINDICES_URL = (
    "https://www.niftyindices.com/Backpage.aspx/getHistoricaldatatabletoString"
)
HTTP_HEADERS = {
    # niftyindices.com sniffs both UA and Referer; sending a browser-like
    # set of headers materially reduces 4xx/empty-response rates.
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_0) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json; charset=UTF-8",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Origin": "https://www.niftyindices.com",
    "Referer": "https://www.niftyindices.com/reports/historical-data",
    "X-Requested-With": "XMLHttpRequest",
}
HTTP_TIMEOUT = (20, 60)  # (connect, read)
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2.0

# How long a cache entry is considered fresh. niftyindices.com publishes
# end-of-day, so within a single calendar day we never need to refetch.
CACHE_FRESHNESS_HOURS = 18


@dataclass(frozen=True)
class BenchmarkPoint:
    """One day's index close, in the same shape as mfapi.in NAV points."""
    date: date
    close: float


@dataclass(frozen=True)
class BenchmarkHistory:
    """Full historical series for one index, oldest-first."""
    name: str
    variant: str  # "PR" or "TRI"
    history: list[BenchmarkPoint]
    fetched_at: datetime
    data_source: str  # e.g. "niftyindices.com"

    @property
    def first_date(self) -> date:
        return self.history[0].date

    @property
    def latest_date(self) -> date:
        return self.history[-1].date


def _sanitize_for_filename(name: str) -> str:
    """``"NIFTY MIDCAP 150"`` -> ``"NIFTY_MIDCAP_150"``."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    return cleaned or "UNKNOWN"


def _format_date_for_endpoint(d: date) -> str:
    """The endpoint wants ``DD-MMM-YYYY`` (e.g. ``01-Jan-2010``)."""
    return d.strftime("%d-%b-%Y")


def _parse_endpoint_date(s: str) -> date:
    """Endpoint returns ``DD MMM YYYY`` (e.g. ``05 Jun 2026``)."""
    return datetime.strptime(s.strip(), "%d %b %Y").date()


def _fetch_raw(
    name: str, *, start: date, end: date,
    attempts: int = RETRY_ATTEMPTS,
    backoff_seconds: float = RETRY_BACKOFF_SECONDS,
) -> list[dict] | None:
    """POST the niftyindices.com endpoint with retries on transient failures."""
    cinfo_payload = {
        "name": name,
        "startDate": _format_date_for_endpoint(start),
        "endDate": _format_date_for_endpoint(end),
        "indexName": name,
    }
    body = {"cinfo": json.dumps(cinfo_payload)}

    for attempt in range(1, attempts + 1):
        try:
            resp = requests.post(
                NIFTYINDICES_URL,
                headers=HTTP_HEADERS,
                data=json.dumps(body),
                timeout=HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            inner = resp.json().get("d")
            if not isinstance(inner, str):
                log.warning(
                    "niftyindices.com returned an unexpected envelope shape "
                    "for %r (attempt %d/%d): %r",
                    name, attempt, attempts, type(inner).__name__,
                )
                return None
            try:
                rows = json.loads(inner)
            except ValueError as exc:
                log.warning(
                    "niftyindices.com returned non-JSON for %r: %s", name, exc
                )
                return None
            if not isinstance(rows, list):
                log.warning(
                    "niftyindices.com inner payload for %r is not a list: %r",
                    name, type(rows).__name__,
                )
                return None
            return rows
        except (requests.ConnectionError, requests.Timeout) as exc:
            if attempt < attempts:
                sleep_s = backoff_seconds * (2 ** (attempt - 1))
                log.info(
                    "niftyindices.com attempt %d/%d failed for %r (%s); "
                    "retrying in %.1fs",
                    attempt, attempts, name, type(exc).__name__, sleep_s,
                )
                time.sleep(sleep_s)
                continue
            log.warning(
                "niftyindices.com fetch failed for %r after %d attempts: %s",
                name, attempts, exc,
            )
            return None
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status is not None and 500 <= status < 600 and attempt < attempts:
                sleep_s = backoff_seconds * (2 ** (attempt - 1))
                log.info(
                    "niftyindices.com HTTP %d for %r (attempt %d/%d); "
                    "retrying in %.1fs",
                    status, name, attempt, attempts, sleep_s,
                )
                time.sleep(sleep_s)
                continue
            log.warning(
                "niftyindices.com fetch failed for %r: HTTP %s",
                name, status if status is not None else "?",
            )
            return None
    return None


def _parse_rows(name: str, rows: list[dict]) -> list[BenchmarkPoint]:
    """Convert the endpoint's raw row dicts into ``BenchmarkPoint``s,
    oldest-first."""
    out: list[BenchmarkPoint] = []
    for row in rows:
        date_str = row.get("HistoricalDate")
        close_str = row.get("CLOSE")
        if not date_str or close_str is None:
            continue
        try:
            d = _parse_endpoint_date(str(date_str))
            close = float(str(close_str).replace(",", ""))
        except ValueError:
            continue
        out.append(BenchmarkPoint(date=d, close=close))
    out.sort(key=lambda p: p.date)
    if not out:
        log.warning("Parsed 0 valid rows for %r out of %d raw rows", name, len(rows))
    return out


def _cache_path(output_dir: Path, name: str, variant: str) -> Path:
    return output_dir / f"{_sanitize_for_filename(name)}_{variant}.json"


def _load_cache(path: Path) -> BenchmarkHistory | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as exc:
        log.warning("Failed to read benchmark cache %s: %s", path, exc)
        return None

    fetched_at_str = raw.get("fetched_at")
    if not fetched_at_str:
        return None
    try:
        fetched_at = datetime.fromisoformat(fetched_at_str)
    except ValueError:
        return None

    history_raw = raw.get("history") or []
    history: list[BenchmarkPoint] = []
    for entry in history_raw:
        try:
            history.append(BenchmarkPoint(
                date=date.fromisoformat(entry["date"]),
                close=float(entry["close"]),
            ))
        except (KeyError, ValueError):
            continue
    if not history:
        return None
    history.sort(key=lambda p: p.date)
    return BenchmarkHistory(
        name=str(raw.get("name") or "?"),
        variant=str(raw.get("variant") or "PR"),
        history=history,
        fetched_at=fetched_at,
        data_source=str(raw.get("data_source") or "niftyindices.com"),
    )


def _save_cache(path: Path, hist: BenchmarkHistory) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": hist.name,
        "variant": hist.variant,
        "data_source": hist.data_source,
        "fetched_at": hist.fetched_at.isoformat(),
        "history": [
            {"date": p.date.isoformat(), "close": p.close} for p in hist.history
        ],
    }
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    tmp_path.replace(path)


def _is_fresh(hist: BenchmarkHistory) -> bool:
    age = datetime.now(timezone.utc) - hist.fetched_at.astimezone(timezone.utc)
    return age < timedelta(hours=CACHE_FRESHNESS_HOURS)


def fetch_benchmark_history(
    name: str, *,
    variant: str = "PR",
    cache_dir: Path,
    start: date = date(2009, 1, 1),
    end: date | None = None,
    force_refresh: bool = False,
) -> BenchmarkHistory | None:
    """Fetch (and cache) a NIFTY index's historical close series.

    ``name`` must match niftyindices.com's index dropdown spelling, e.g.
    ``"NIFTY 500"`` or ``"NIFTY MIDCAP 150"``.

    Returns ``None`` only on persistent fetch failure (after retries) when
    no usable cache is present.
    """
    cache_path = _cache_path(cache_dir, name, variant)
    if not force_refresh:
        cached = _load_cache(cache_path)
        if cached is not None and _is_fresh(cached):
            log.info(
                "Using cached benchmark %r (variant=%s, %d points, fetched %s)",
                cached.name, cached.variant, len(cached.history),
                cached.fetched_at.isoformat(timespec="seconds"),
            )
            return cached

    if end is None:
        end = date.today()

    log.info(
        "Fetching benchmark history for %r (variant=%s, range=%s..%s) "
        "from niftyindices.com",
        name, variant, start, end,
    )
    rows = _fetch_raw(name, start=start, end=end)
    if rows is None or not rows:
        # Fall back to stale cache if any; better than nothing.
        cached = _load_cache(cache_path)
        if cached is not None:
            log.warning(
                "Live fetch failed for %r; using stale cache from %s",
                name, cached.fetched_at.isoformat(timespec="seconds"),
            )
            return cached
        log.error("No live data and no cache available for %r", name)
        return None

    history = _parse_rows(name, rows)
    if not history:
        return None

    hist = BenchmarkHistory(
        name=name,
        variant=variant,
        history=history,
        fetched_at=datetime.now(timezone.utc),
        data_source="niftyindices.com",
    )
    try:
        _save_cache(cache_path, hist)
    except OSError as exc:
        log.warning("Could not write benchmark cache %s: %s", cache_path, exc)
    return hist
