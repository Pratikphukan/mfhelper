"""Market regime and valuation context for dip-buying alerts.

Classifies the broad market from the NIFTY 500 and India VIX, and reads the
Nifty 50 P/E. Nothing here touches alert objects; ``regime_filter`` applies the
context to them. Every external fetch is injectable so tests never hit the
network, and every failure degrades to a NEUTRAL "context unavailable" result
instead of raising, so alerts keep flowing unfiltered.

Regime rules, first match wins (``classify_raw``):

1. BEAR       index < 200D SMA and the 200D SMA is lower than ``slope_lookback_days`` ago
2. CORRECTION smoothed VIX >= ``vix_high``
3. UPTREND    smoothed VIX < ``vix_low`` and index > 50D SMA
4. NEUTRAL    everything else (alert set unchanged)

The VIX is the average of the last ``vix_smoothing_days`` sessions. A change of
regime only takes effect after it has held for ``confirm_days`` consecutive
sessions. This is computed by replaying the recent history on every run, so no
state file is needed and a re-run on the same data always gives the same answer.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
import html
import json
import logging
from pathlib import Path
from typing import Callable

from mfhelper.benchmarks import BenchmarkHistory, BenchmarkPoint, fetch_benchmark_history
from mfhelper.config import RegimeSettings

log = logging.getLogger(__name__)

# How many recent sessions are replayed to apply the confirmation rule.
REPLAY_SESSIONS = 60
# Calendar days of history requested (200D SMA + slope lookback + replay window, with margin).
HISTORY_CALENDAR_DAYS = 800

NSE_HOME_URL = "https://www.nseindia.com"
NSE_ALL_INDICES_URL = "https://www.nseindia.com/api/allIndices"
PE_CACHE_FILENAME = "nifty50_pe.json"
# Sanity band: anything outside this is a parsing problem, not a valuation.
PE_PLAUSIBLE_RANGE = (5.0, 100.0)


class Regime(str, Enum):
    BEAR = "BEAR"
    CORRECTION = "CORRECTION"
    UPTREND = "UPTREND"
    NEUTRAL = "NEUTRAL"


REGIME_STANCE = {
    Regime.BEAR: "capital preservation: only capitulation buys are shown",
    Regime.CORRECTION: "conservative: Tier-1 dips are suppressed",
    Regime.UPTREND: "aggressive: Tier-1 dips are high-conviction",
    Regime.NEUTRAL: "standard rules",
}


@dataclass(frozen=True)
class Valuation:
    pe: float | None
    state: str  # "stretched" | "cheap" | "fair" | "unknown"
    source: str | None = None  # "nse" | "nse_cache" | "manual"
    as_of: date | None = None
    stale: bool = False


@dataclass(frozen=True)
class MarketContext:
    available: bool
    regime: Regime
    valuation: Valuation
    raw_regime: Regime | None = None
    pending_regime: Regime | None = None
    pending_days: int = 0
    confirm_days: int = 3
    as_of: date | None = None
    index_close: float | None = None
    sma_short: float | None = None
    sma_long: float | None = None
    vix_avg: float | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class SuppressedSignal:
    scheme_code: str
    fund_name: str
    label: str
    reason: str


UNKNOWN_VALUATION = Valuation(pe=None, state="unknown")


# --- classification -------------------------------------------------------------------


def _sma(values: list[float], window: int, end_index: int) -> float:
    chunk = values[end_index - window + 1 : end_index + 1]
    return sum(chunk) / window


def classify_raw(closes: list[float], index: int, vix_avg: float | None, cfg: RegimeSettings) -> Regime | None:
    """Raw (unconfirmed) regime for ``closes[index]``; ``None`` if there is too little history."""
    if index < cfg.long_sma_days - 1 + cfg.slope_lookback_days:
        return None
    close = closes[index]
    sma_long = _sma(closes, cfg.long_sma_days, index)
    sma_long_before = _sma(closes, cfg.long_sma_days, index - cfg.slope_lookback_days)
    if close < sma_long and sma_long < sma_long_before:
        return Regime.BEAR
    if vix_avg is not None:
        if vix_avg >= cfg.vix_high:
            return Regime.CORRECTION
        if vix_avg < cfg.vix_low and close > _sma(closes, cfg.short_sma_days, index):
            return Regime.UPTREND
    return Regime.NEUTRAL


def vix_average_asof(vix: list[BenchmarkPoint], day: date, sessions: int) -> float | None:
    """Mean of the last ``sessions`` VIX closes on or before ``day`` (``None`` if too few)."""
    dates = [p.date for p in vix]
    end = bisect_right(dates, day)
    if end < sessions:
        return None
    window = vix[end - sessions : end]
    return sum(p.close for p in window) / sessions


@dataclass(frozen=True)
class ReplayResult:
    regime: Regime
    raw_regime: Regime
    pending_regime: Regime | None
    pending_days: int
    as_of: date
    index_close: float
    sma_short: float
    sma_long: float
    vix_avg: float | None


def replay_regime(
    index: list[BenchmarkPoint],
    vix: list[BenchmarkPoint],
    cfg: RegimeSettings,
    *,
    sessions: int = REPLAY_SESSIONS,
) -> ReplayResult | None:
    """Apply the confirmation rule over the last ``sessions`` index sessions.

    The oldest replayed session's raw regime is taken as already confirmed, so the
    result is a pure function of the supplied history.
    """
    closes = [p.close for p in index]
    first_valid = cfg.long_sma_days - 1 + cfg.slope_lookback_days
    last = len(closes) - 1
    if last < first_valid:
        return None
    start = max(first_valid, last - sessions + 1)

    effective: Regime | None = None
    pending: Regime | None = None
    pending_days = 0
    raw: Regime | None = None
    vix_avg: float | None = None
    for i in range(start, last + 1):
        vix_avg = vix_average_asof(vix, index[i].date, cfg.vix_smoothing_days)
        raw = classify_raw(closes, i, vix_avg, cfg)
        assert raw is not None  # i >= first_valid
        if effective is None:
            effective = raw
            continue
        if raw == effective:
            pending, pending_days = None, 0
            continue
        if raw == pending:
            pending_days += 1
        else:
            pending, pending_days = raw, 1
        if pending_days >= cfg.confirm_days:
            effective, pending, pending_days = raw, None, 0

    assert effective is not None and raw is not None
    return ReplayResult(
        regime=effective,
        raw_regime=raw,
        pending_regime=pending,
        pending_days=pending_days,
        as_of=index[last].date,
        index_close=closes[last],
        sma_short=_sma(closes, cfg.short_sma_days, last),
        sma_long=_sma(closes, cfg.long_sma_days, last),
        vix_avg=vix_avg,
    )


# --- valuation ------------------------------------------------------------------------


def fetch_nifty50_pe_from_nse(timeout: float = 15.0) -> float | None:
    """Best-effort read of the Nifty 50 P/E from NSE's public ``allIndices`` endpoint.

    NSE needs a cookie from the home page first and may block some networks, so any
    failure returns ``None`` and the caller falls back to cache / manual config.
    """
    try:
        import requests

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": NSE_HOME_URL,
        }
        session = requests.Session()
        session.headers.update(headers)
        session.get(NSE_HOME_URL, timeout=timeout)
        response = session.get(NSE_ALL_INDICES_URL, timeout=timeout)
        response.raise_for_status()
        for row in response.json().get("data", []):
            if str(row.get("index", "")).strip().upper() == "NIFTY 50":
                return _plausible_pe(row.get("pe"))
    except Exception as exc:  # network, JSON, or schema drift: all mean "no live value"
        log.warning("Could not read Nifty 50 P/E from NSE: %s", exc)
    return None


def _plausible_pe(value: object) -> float | None:
    try:
        pe = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    low, high = PE_PLAUSIBLE_RANGE
    return pe if low <= pe <= high else None


def _read_pe_cache(path: Path) -> tuple[float, date] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        pe = _plausible_pe(raw["pe"])
        fetched_on = date.fromisoformat(raw["fetched_on"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return (pe, fetched_on) if pe is not None else None


def _write_pe_cache(path: Path, pe: float, fetched_on: date) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"pe": pe, "fetched_on": fetched_on.isoformat(), "source": "nse"}, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
    except OSError as exc:
        log.warning("Could not write P/E cache %s: %s", path, exc)


def _valuation_state(pe: float, cfg: RegimeSettings) -> str:
    if pe > cfg.pe_stretched:
        return "stretched"
    if pe < cfg.pe_cheap:
        return "cheap"
    return "fair"


def resolve_valuation(
    cfg: RegimeSettings,
    *,
    cache_dir: Path,
    today: date,
    fetch_pe: Callable[[], float | None] = fetch_nifty50_pe_from_nse,
) -> Valuation:
    """Live NSE value, else a recent cached NSE value, else the manual config value, else unknown."""
    cache_path = cache_dir / PE_CACHE_FILENAME

    live = _plausible_pe(fetch_pe())
    if live is not None:
        _write_pe_cache(cache_path, live, today)
        return Valuation(live, _valuation_state(live, cfg), source="nse", as_of=today)

    cached = _read_pe_cache(cache_path)
    if cached is not None:
        pe, fetched_on = cached
        if (today - fetched_on).days <= cfg.pe_stale_days:
            return Valuation(pe, _valuation_state(pe, cfg), source="nse_cache", as_of=fetched_on)

    if cfg.pe_manual is not None:
        stale = cfg.pe_manual_as_of is None or (today - cfg.pe_manual_as_of).days > cfg.pe_stale_days
        return Valuation(
            cfg.pe_manual, _valuation_state(cfg.pe_manual, cfg), source="manual",
            as_of=cfg.pe_manual_as_of, stale=stale,
        )
    return UNKNOWN_VALUATION


# --- context --------------------------------------------------------------------------


def _unavailable(reason: str, valuation: Valuation, confirm_days: int) -> MarketContext:
    return MarketContext(
        available=False, regime=Regime.NEUTRAL, valuation=valuation,
        confirm_days=confirm_days, notes=(reason,),
    )


def load_series(
    ticker: str,
    *,
    cache_dir: Path,
    today: date,
    fetch_history: Callable[..., BenchmarkHistory | None] = fetch_benchmark_history,
) -> list[BenchmarkPoint]:
    """Recent daily closes for ``ticker`` (empty list on any failure)."""
    start = today - timedelta(days=HISTORY_CALENDAR_DAYS)
    try:
        history = fetch_history(ticker, cache_dir=cache_dir, start=start, end=today)
    except Exception as exc:
        log.warning("Market data fetch failed for %s: %s", ticker, exc)
        return []
    return list(history.history) if history else []


@dataclass(frozen=True)
class HistoryRow:
    day: date
    index_close: float
    vix_avg: float | None
    raw: Regime
    effective: Regime


def regime_history(
    index: list[BenchmarkPoint], vix: list[BenchmarkPoint], cfg: RegimeSettings, days: int
) -> list[HistoryRow]:
    """Raw and confirmed regime for each of the last ``days`` sessions, oldest first."""
    rows: list[HistoryRow] = []
    for end in range(max(0, len(index) - days), len(index)):
        result = replay_regime(index[: end + 1], vix, cfg)
        if result is None:
            continue
        rows.append(HistoryRow(result.as_of, result.index_close, result.vix_avg, result.raw_regime, result.regime))
    return rows


def build_market_context(
    cfg: RegimeSettings,
    *,
    cache_dir: Path,
    today: date | None = None,
    fetch_history: Callable[..., BenchmarkHistory | None] = fetch_benchmark_history,
    fetch_pe: Callable[[], float | None] = fetch_nifty50_pe_from_nse,
) -> MarketContext:
    """Build today's market context. Never raises; failures yield NEUTRAL with a note."""
    today = today or date.today()
    try:
        valuation = resolve_valuation(cfg, cache_dir=cache_dir, today=today, fetch_pe=fetch_pe)
    except Exception as exc:
        log.warning("Valuation lookup failed: %s", exc)
        valuation = UNKNOWN_VALUATION

    def load(ticker: str) -> list[BenchmarkPoint]:
        return load_series(ticker, cache_dir=cache_dir, today=today, fetch_history=fetch_history)

    index = load(cfg.index_ticker)
    if not index:
        return _unavailable(f"no {cfg.index_ticker} data", valuation, cfg.confirm_days)
    index_age = (today - index[-1].date).days
    if index_age > cfg.max_data_age_days:
        return _unavailable(
            f"{cfg.index_ticker} data is {index_age} days old", valuation, cfg.confirm_days
        )

    notes: list[str] = []
    vix = load(cfg.vix_ticker)
    if not vix:
        notes.append(f"no {cfg.vix_ticker} data")
    elif (today - vix[-1].date).days > cfg.max_data_age_days:
        notes.append(f"{cfg.vix_ticker} data is {(today - vix[-1].date).days} days old")
        vix = []

    result = replay_regime(index, vix, cfg)
    if result is None:
        return _unavailable(
            f"only {len(index)} {cfg.index_ticker} sessions; need at least "
            f"{cfg.long_sma_days + cfg.slope_lookback_days}",
            valuation, cfg.confirm_days,
        )
    return MarketContext(
        available=True,
        regime=result.regime,
        valuation=valuation,
        raw_regime=result.raw_regime,
        pending_regime=result.pending_regime,
        pending_days=result.pending_days,
        confirm_days=cfg.confirm_days,
        as_of=result.as_of,
        index_close=result.index_close,
        sma_short=result.sma_short,
        sma_long=result.sma_long,
        vix_avg=result.vix_avg,
        notes=tuple(notes),
    )


# --- rendering ------------------------------------------------------------------------


def valuation_text(valuation: Valuation) -> str:
    if valuation.pe is None:
        return "Nifty 50 P/E unavailable"
    text = f"Nifty 50 P/E {valuation.pe:.1f} ({valuation.state})"
    if valuation.source == "manual":
        when = valuation.as_of.isoformat() if valuation.as_of else "no date"
        text += f", manual value as of {when}"
        if valuation.stale:
            text += " - STALE, please update"
    elif valuation.source == "nse_cache" and valuation.as_of:
        text += f", cached {valuation.as_of.isoformat()}"
    return text


def banner_text(context: MarketContext) -> str:
    """One-line plain-text summary used in the email banner and the CLI."""
    if not context.available:
        reason = "; ".join(context.notes) or "unknown reason"
        return (
            f"Market context unavailable ({reason}): alerts are shown without regime filtering. "
            f"{valuation_text(context.valuation)}."
        )
    parts = [f"Market regime: {context.regime.value} ({REGIME_STANCE[context.regime]})"]
    details = []
    if context.vix_avg is not None:
        details.append(f"VIX avg {context.vix_avg:.1f}")
    if context.index_close is not None and context.sma_long is not None:
        side = "above" if context.index_close > context.sma_long else "below"
        details.append(f"index {side} 200D SMA")
    if details:
        parts.append(", ".join(details))
    if context.pending_regime is not None:
        parts.append(
            f"{context.pending_regime.value} forming, day {context.pending_days} of {context.confirm_days}"
        )
    parts.append(valuation_text(context.valuation))
    parts.extend(context.notes)
    return " | ".join(parts)


def render_regime_banner_html(context: MarketContext | None) -> str:
    if context is None:
        return ""
    return (
        '<p style="margin:0 0 12px 0;padding:8px 12px;background:#f1f5f9;border-left:4px solid #64748b;'
        'font-size:13px;color:#334155;">'
        f"{html.escape(banner_text(context))}</p>"
    )


def render_suppressed_html(suppressed: list[SuppressedSignal] | None) -> str:
    if not suppressed:
        return ""
    items = "".join(
        f"<li><strong>{html.escape(s.fund_name)}</strong>: {html.escape(s.label)} "
        f"<span style=\"color:#64748b;\">({html.escape(s.reason)})</span></li>"
        for s in suppressed
    )
    return (
        '<div style="margin-top:16px;padding:8px 12px;background:#f8fafc;border:1px solid #e2e8f0;'
        'font-size:12px;color:#475569;">'
        f"<p style=\"margin:0 0 6px 0;\"><strong>Suppressed by market regime ({len(suppressed)})</strong></p>"
        f'<ul style="margin:0;padding-left:18px;">{items}</ul></div>'
    )
