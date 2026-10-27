"""Yahoo Finance benchmark history fetcher with local caching.

Fetches historical NIFTY index data and constructed benchmarks via Yahoo
Finance (``yfinance``). Used for fund-vs-benchmark comparison: each fund's
rolling-window metrics get a benchmark counterpart so we can compute alpha
(active return), beat-rate, and information-ratio distributions.

Why yfinance over niftyindices.com:
- niftyindices.com blocks datacenter IP ranges (GitHub Actions / Azure),
  causing all benchmark fetches to fail silently in CI.
- Yahoo Finance does not block datacenter IPs and is well-maintained.
- Data quality is identical: both expose PR (Price Return) daily closes
  with full history back to ~Jan 2009 for all major NIFTY indices.

Yahoo Finance tickers for supported NIFTY indices:

    NIFTY 50         →  ^NSEI
    NIFTY 200        →  ^CNX200
    NIFTY 500        →  ^CRSLDX
    NIFTY MIDCAP 150 →  ^NSEMDCP50

Synthetic benchmark: ``GOLD_INR``
    The domestic gold price in INR is not available as a direct ticker.
    It is constructed as:

        gold_inr = GC=F (COMEX gold futures, USD/troy oz)
                 × INR=X (USD/INR spot rate)

    Both series are fetched from yfinance and aligned on common dates.
    Forward-fill (max 3 days) handles holiday mismatches between US and
    Indian markets. Use ``index_name: "GOLD_INR"`` in benchmarks.yaml
    to enable this construction for a fund.

What we get vs. what we'd ideally want:
- Yahoo Finance exposes PR (Price Return) data for equity indices. The
  Total Return Index (TRI) variant is not available for free. PR
  understates the benchmark by the index dividend yield (~1-1.5%/yr for
  Indian equity indices). This gap is documented in each fund's
  vs_benchmark.data_quality.note in the per-fund JSON.
- For gold, GC=F is the front-month futures price (not spot). It includes
  a small contango premium and rolls periodically. For daily NAV
  comparison this difference is negligible.

Local caching:
- Each benchmark is cached at
  ``data/benchmark_history/<sanitized_name>_<variant>.json``.
- A fetch is reused for ``CACHE_FRESHNESS_HOURS`` hours. Between daily
  CI runs (~24h apart) the cache is always stale so yfinance fetches
  fresh. For manual re-triggers within the same day the cache is warm
  and the fetch is skipped.
- The cache writer is atomic (.tmp + rename).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)

# How long a cache entry is considered fresh.
CACHE_FRESHNESS_HOURS = 18

YFINANCE_START_DATE = date(2009, 1, 1)

# Synthetic sentinel for the domestic gold price in INR (GC=F × INR=X).
GOLD_INR_SENTINEL = "GOLD_INR"
GOLD_FUTURES_TICKER = "GC=F"
USDINR_TICKER = "INR=X"
# Max days to forward-fill gaps when aligning gold and forex series.
# 3 days covers any long weekend in either US or Indian markets.
MAX_FFILL_DAYS = 3


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
    data_source: str  # e.g. "yahoo_finance"

    @property
    def first_date(self) -> date:
        return self.history[0].date

    @property
    def latest_date(self) -> date:
        return self.history[-1].date


def _sanitize_for_filename(name: str) -> str:
    """``"^CRSLDX"`` -> ``"CRSLDX"``."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    return cleaned or "UNKNOWN"


def _fetch_yfinance(
    ticker: str,
    *,
    start: date,
    end: date,
) -> list[BenchmarkPoint] | None:
    """Fetch daily closes from Yahoo Finance for ``ticker``.

    Returns a list of ``BenchmarkPoint`` sorted oldest-first, or ``None``
    on any failure.
    """
    try:
        df = yf.download(
            ticker,
            start=start.isoformat(),
            # yfinance end date is exclusive so add one day
            end=(end + timedelta(days=1)).isoformat(),
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
            close_val = row["Close"]
            # yfinance may return a Series when multiple tickers are passed;
            # squeeze to scalar just in case.
            if hasattr(close_val, "iloc"):
                close_val = close_val.iloc[0]
            close = float(close_val)
            points.append(BenchmarkPoint(date=ts.date(), close=close))
        except (KeyError, ValueError, TypeError):
            continue

    points.sort(key=lambda p: p.date)
    if not points:
        log.warning("yfinance returned 0 valid rows for %r", ticker)
        return None

    log.info(
        "yfinance fetched %d points for %r (%s → %s)",
        len(points), ticker, points[0].date, points[-1].date,
    )
    return points


def _fetch_gold_inr(
    *,
    start: date,
    end: date,
) -> list[BenchmarkPoint] | None:
    """Construct the domestic gold price in INR as GC=F × INR=X.

    Fetches COMEX gold futures (USD/troy oz) and USD/INR spot rate from
    Yahoo Finance, aligns on common dates with a forward-fill of up to
    ``MAX_FFILL_DAYS`` to handle US/India holiday mismatches, then
    multiplies to produce INR-denominated gold price per troy oz.
    """
    try:
        df_gold = yf.download(
            GOLD_FUTURES_TICKER,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            progress=False,
            auto_adjust=True,
        )
        df_inr = yf.download(
            USDINR_TICKER,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            progress=False,
            auto_adjust=True,
        )
    except Exception as exc:
        log.warning("yfinance download failed for gold INR construction: %s", exc)
        return None

    if df_gold.empty or df_inr.empty:
        log.warning(
            "yfinance returned empty data for gold construction "
            "(gold empty: %s, inr empty: %s)",
            df_gold.empty, df_inr.empty,
        )
        return None

    gold_usd = df_gold["Close"].squeeze().rename("gold_usd")
    usd_inr = df_inr["Close"].squeeze().rename("usd_inr")

    # Outer join → forward-fill gaps → drop any remaining NaN at edges.
    combined = pd.concat([gold_usd, usd_inr], axis=1, sort=True)
    combined = combined.ffill(limit=MAX_FFILL_DAYS).dropna()

    if combined.empty:
        log.warning("No overlapping dates between GC=F and INR=X after alignment")
        return None

    points: list[BenchmarkPoint] = []
    for ts, row in combined.iterrows():
        try:
            gold_inr = float(row["gold_usd"]) * float(row["usd_inr"])
            points.append(BenchmarkPoint(date=ts.date(), close=gold_inr))
        except (ValueError, TypeError):
            continue

    points.sort(key=lambda p: p.date)
    if not points:
        log.warning("No valid gold INR data points after construction")
        return None

    log.info(
        "Constructed domestic gold price (INR): %d points (%s → %s), "
        "latest: %.2f INR/troy oz",
        len(points), points[0].date, points[-1].date, points[-1].close,
    )
    return points


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
        data_source=str(raw.get("data_source") or "yahoo_finance"),
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
    name: str,
    *,
    variant: str = "PR",
    cache_dir: Path,
    start: date = YFINANCE_START_DATE,
    end: date | None = None,
    force_refresh: bool = False,
) -> BenchmarkHistory | None:
    """Fetch (and cache) a NIFTY index's historical close series via yfinance.

    ``name`` is the Yahoo Finance ticker, e.g. ``"^CRSLDX"`` for NIFTY 500.

    Returns ``None`` only on persistent fetch failure when no usable cache
    is present.
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

    if name == GOLD_INR_SENTINEL:
        log.info(
            "Constructing domestic gold price in INR (GC=F × INR=X, "
            "range=%s..%s)",
            start, end,
        )
        history = _fetch_gold_inr(start=start, end=end)
        data_source = "yahoo_finance:GC=F×INR=X"
    else:
        log.info(
            "Fetching benchmark history for %r (variant=%s, range=%s..%s) "
            "from Yahoo Finance",
            name, variant, start, end,
        )
        history = _fetch_yfinance(name, start=start, end=end)
        data_source = "yahoo_finance"

    if not history:
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

    hist = BenchmarkHistory(
        name=name,
        variant=variant,
        history=history,
        fetched_at=datetime.now(timezone.utc),
        data_source=data_source,
    )
    try:
        _save_cache(cache_path, hist)
    except OSError as exc:
        log.warning("Could not write benchmark cache %s: %s", cache_path, exc)
    return hist
