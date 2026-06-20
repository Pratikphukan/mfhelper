"""Derived metrics computed from a fund's NAV history."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

from mfhelper.mfapi import NavHistoryPoint

WINDOW_52_WEEKS_DAYS = 365
SMA_200D_WINDOW = 200
RSI_DEFAULT_PERIOD = 14


def distance_from_52w_high(
    history: Iterable[NavHistoryPoint],
    current_nav: float,
    current_date: date,
    *,
    window_days: int = WINDOW_52_WEEKS_DAYS,
) -> float | None:
    """Percent below the 52-week high. Always non-positive.

    The reference high is taken as the maximum NAV in the trailing
    ``window_days`` ending at ``current_date`` (inclusive), with
    ``current_nav`` itself included in the comparison set so that a fresh
    all-time-high produces 0.00 rather than a positive number.

    Returns ``None`` if no history data is available within the window or
    if the high evaluates to zero (degenerate input).
    """
    cutoff = current_date - timedelta(days=window_days)
    in_window_navs = [p.nav for p in history if cutoff <= p.nav_date <= current_date]
    if not in_window_navs:
        return None

    high = max(max(in_window_navs), current_nav)
    if high <= 0:
        return None

    return round((current_nav - high) / high * 100, 4)


def distance_from_200d_sma(
    history: Iterable[NavHistoryPoint],
    current_nav: float,
    current_date: date,
    *,
    window_trading_days: int = SMA_200D_WINDOW,
) -> float | None:
    """Percent distance from the 200-day Simple Moving Average.

    The SMA is computed over the most recent ``window_trading_days``
    NAV-publish days ending at ``current_date`` (inclusive). ``current_nav``
    itself is treated as today's NAV: any history entry on ``current_date``
    is dropped in favour of ``current_nav`` (which may have come from AMFI
    rather than mfapi).

    The 200-day window is the classical long-term trend filter:
    ``current_nav`` above the 200D SMA indicates a longer-running uptrend
    context; below indicates a downtrend context. The function works for
    any past ``current_date`` (any history point with ``nav_date >=
    current_date`` is ignored), which makes it usable both for today's
    value and for historical backfill.

    Returns ``None`` if fewer than ``window_trading_days`` data points are
    available, or if the resulting SMA is zero. Otherwise returns
    ``(current_nav - sma) / sma * 100``, rounded to 4 decimals: positive
    when current NAV is above the SMA, negative when below.
    """
    series = [(p.nav_date, p.nav) for p in history if p.nav_date < current_date]
    series.append((current_date, current_nav))
    series.sort(key=lambda entry: entry[0], reverse=True)

    if len(series) < window_trading_days:
        return None

    window_navs = [nav for _, nav in series[:window_trading_days]]
    sma = sum(window_navs) / len(window_navs)
    if sma <= 0:
        return None

    return round((current_nav - sma) / sma * 100, 4)


def rsi(
    history: Iterable[NavHistoryPoint],
    current_nav: float,
    current_date: date,
    *,
    period: int = RSI_DEFAULT_PERIOD,
) -> float | None:
    """Wilder's Relative Strength Index over the last ``period`` NAV deltas.

    Implementation:

    - Build a chronological NAV series ending at ``current_date``: history
      entries with ``nav_date < current_date`` followed by ``current_nav``.
      Any history entry on ``current_date`` is dropped in favour of
      ``current_nav`` (which may have come from AMFI rather than mfapi).
    - Compute consecutive deltas. ``period`` deltas are needed, which means
      ``period + 1`` data points.
    - Seed the average gain/loss with the simple mean over the first
      ``period`` deltas (Wilder's canonical initialization), then apply
      Wilder smoothing for each subsequent delta::

          avg_new = (avg_prev * (period - 1) + value_today) / period

    - ``RS = avg_gain / avg_loss``; ``RSI = 100 - 100 / (1 + RS)``.
    - If the trailing ``avg_loss`` is exactly zero (all-up window),
      RSI is defined as ``100.0``.

    Returns ``None`` if fewer than ``period + 1`` data points are available.
    """
    if period < 1:
        raise ValueError("period must be >= 1")

    relevant = sorted(
        (p for p in history if p.nav_date < current_date),
        key=lambda p: p.nav_date,
    )
    series_navs = [p.nav for p in relevant] + [current_nav]

    if len(series_navs) < period + 1:
        return None

    deltas = [series_navs[i] - series_navs[i - 1] for i in range(1, len(series_navs))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for g, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - 100.0 / (1.0 + rs), 2)
