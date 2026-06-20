"""Compute fund-level analytics from a daily NAV history.

The metrics we report and the conventions we use:

- **1Y return** -- *absolute* (point-to-point) percentage change over the
  trailing 365 calendar days. Industry tools (Moneycontrol, ValueResearch,
  Morningstar India) report 1Y as absolute; only multi-year windows are
  CAGR. Returned as a percent, e.g. ``18.42`` means ``+18.42%``.

- **3Y / 5Y / 7Y / 10Y returns** -- *CAGR* (compound annual growth rate)
  over those trailing windows. Returned as an annualized percent.

- **SD** -- *annualized* standard deviation of daily log returns over the
  most recent 3 years of NAV history (or the full history if shorter).
  Annualization factor: ``sqrt(252)`` (252 trading days in a typical
  Indian-equity year). Returned as a percent.

- **Sharpe ratio** -- ``(CAGR_3Y - risk_free_rate) / SD``. The 3Y CAGR
  numerator + 3Y SD denominator pair is the standard ValueResearch /
  Moneycontrol convention. Risk-free rate defaults to 7% (RBI repo proxy).
  Unitless. Higher = better risk-adjusted return.

- **Sortino ratio** -- ``(CAGR_3Y - risk_free_rate) / downside_deviation``,
  where downside deviation is the annualized stdev of *only the negative*
  daily log returns over the same 3Y window. Sortino "punishes" only the
  bad volatility, not the good kind. Unitless.

Window resolution:
- For each return window, we find the NAV closest to ``today - window_days``
  (within a 7-day tolerance). If no close-enough anchor exists, that window
  returns ``None`` -- the cell is left blank in the output sheet.
- All inputs are ``mfhelper.mfapi.NavHistoryPoint`` lists (newest first,
  same shape ``mfhelper.mfapi.fetch_history`` already returns).

Everything is pure Python, NumPy not required.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import log, sqrt
from typing import Iterable

from mfhelper.mfapi import NavHistoryPoint

# Trading-day annualization factor. Indian markets observe ~252 trading
# days per year after weekends and ~12 trading holidays.
TRADING_DAYS_PER_YEAR = 252

# Default risk-free rate (annual percent) for Sharpe / Sortino.
DEFAULT_RISK_FREE_RATE_PCT = 7.0

# Window over which SD / Sharpe / Sortino are computed.
RISK_WINDOW_YEARS = 3
RISK_WINDOW_DAYS = 365 * RISK_WINDOW_YEARS

# When matching "NAV ``window_days`` ago", how far we'll search either side
# of the target date for the closest available NAV publish day. Markets
# close on weekends and holidays, so a few days of slack is essential.
ANCHOR_TOLERANCE_DAYS = 7


@dataclass(frozen=True)
class FundAnalytics:
    """All computed metrics for a single fund. Any field may be ``None``
    if the underlying history was insufficient or degenerate."""
    return_1y_abs_pct: float | None
    cagr_3y_pct: float | None
    cagr_5y_pct: float | None
    cagr_7y_pct: float | None
    cagr_10y_pct: float | None
    sd_pct: float | None
    sharpe: float | None
    sortino: float | None


# --- internal helpers --------------------------------------------------------


def _nav_at_or_near(
    history: list[NavHistoryPoint], target: date,
    *, tolerance_days: int = ANCHOR_TOLERANCE_DAYS,
) -> NavHistoryPoint | None:
    """Return the NAV publish day closest to ``target``, within
    ``tolerance_days``. ``history`` is newest-first per mfapi convention."""
    if not history:
        return None
    best: NavHistoryPoint | None = None
    best_gap = tolerance_days + 1
    for point in history:
        gap = abs((point.nav_date - target).days)
        if gap > tolerance_days:
            continue
        if gap < best_gap:
            best = point
            best_gap = gap
            if gap == 0:
                break
    return best


def _absolute_return_pct(start_nav: float, end_nav: float) -> float | None:
    if start_nav <= 0:
        return None
    return (end_nav / start_nav - 1.0) * 100.0


def _cagr_pct(start_nav: float, end_nav: float, years: float) -> float | None:
    """Compound annual growth rate as a percent. ``years`` should match
    the actual time elapsed between ``start_nav`` and ``end_nav``."""
    if start_nav <= 0 or end_nav <= 0 or years <= 0:
        return None
    return ((end_nav / start_nav) ** (1.0 / years) - 1.0) * 100.0


def _daily_log_returns(history: list[NavHistoryPoint]) -> list[float]:
    """Daily log returns over ``history`` (which is newest-first).

    We sort oldest-first internally, then iterate. Returns one fewer entry
    than the input length. Skips zero/negative NAVs defensively.
    """
    if len(history) < 2:
        return []
    chrono = sorted(history, key=lambda p: p.nav_date)
    out: list[float] = []
    prev = chrono[0].nav
    for p in chrono[1:]:
        if prev > 0 and p.nav > 0:
            out.append(log(p.nav / prev))
        prev = p.nav
    return out


def _stdev(values: list[float]) -> float | None:
    """Sample standard deviation. Returns ``None`` for n<2."""
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return sqrt(var)


def _downside_deviation(values: list[float]) -> float | None:
    """Annualization-friendly downside deviation: stdev computed over only
    the negative entries, with the mean fixed at zero (the conventional
    "deviations from a target return of 0" formulation)."""
    negatives = [v for v in values if v < 0]
    n = len(negatives)
    if n < 2:
        return None
    var = sum(v * v for v in negatives) / n
    return sqrt(var)


# --- public API --------------------------------------------------------------


def compute_analytics(
    history: Iterable[NavHistoryPoint],
    *,
    as_of: date | None = None,
    risk_free_rate_pct: float = DEFAULT_RISK_FREE_RATE_PCT,
) -> FundAnalytics:
    """Compute all metrics for a single fund.

    ``history`` is the full NAV history (mfapi shape, newest-first OK).
    ``as_of`` defaults to the most recent NAV date in the history (so a
    weekend run still produces results based on Friday's NAV).
    """
    history_list = list(history)
    if not history_list:
        return _empty_result()

    history_sorted = sorted(history_list, key=lambda p: p.nav_date, reverse=True)
    end_point = history_sorted[0]
    if as_of is None:
        as_of = end_point.nav_date

    # 1Y absolute, 3Y/5Y/7Y/10Y CAGR.
    def window_metric(years: int, *, cagr: bool) -> float | None:
        target = as_of - timedelta(days=365 * years)
        anchor = _nav_at_or_near(history_sorted, target)
        if anchor is None or anchor.nav <= 0:
            return None
        elapsed_years = (as_of - anchor.nav_date).days / 365.0
        if elapsed_years <= 0:
            return None
        if cagr:
            return _cagr_pct(anchor.nav, end_point.nav, elapsed_years)
        return _absolute_return_pct(anchor.nav, end_point.nav)

    return_1y_abs = window_metric(1, cagr=False)
    cagr_3y = window_metric(3, cagr=True)
    cagr_5y = window_metric(5, cagr=True)
    cagr_7y = window_metric(7, cagr=True)
    cagr_10y = window_metric(10, cagr=True)

    # SD / Sharpe / Sortino on the trailing 3Y of daily returns.
    risk_cutoff = as_of - timedelta(days=RISK_WINDOW_DAYS)
    risk_window = [p for p in history_sorted if risk_cutoff <= p.nav_date <= as_of]
    log_returns = _daily_log_returns(risk_window)

    sd_daily = _stdev(log_returns)
    sd_annualized_pct: float | None = None
    if sd_daily is not None:
        sd_annualized_pct = sd_daily * sqrt(TRADING_DAYS_PER_YEAR) * 100.0

    sharpe: float | None = None
    sortino: float | None = None
    if cagr_3y is not None and sd_annualized_pct and sd_annualized_pct > 0:
        sharpe = (cagr_3y - risk_free_rate_pct) / sd_annualized_pct

    if cagr_3y is not None and log_returns:
        downside_daily = _downside_deviation(log_returns)
        if downside_daily and downside_daily > 0:
            downside_annualized_pct = (
                downside_daily * sqrt(TRADING_DAYS_PER_YEAR) * 100.0
            )
            sortino = (cagr_3y - risk_free_rate_pct) / downside_annualized_pct

    return FundAnalytics(
        return_1y_abs_pct=_round_or_none(return_1y_abs, 2),
        cagr_3y_pct=_round_or_none(cagr_3y, 2),
        cagr_5y_pct=_round_or_none(cagr_5y, 2),
        cagr_7y_pct=_round_or_none(cagr_7y, 2),
        cagr_10y_pct=_round_or_none(cagr_10y, 2),
        sd_pct=_round_or_none(sd_annualized_pct, 2),
        sharpe=_round_or_none(sharpe, 2),
        sortino=_round_or_none(sortino, 2),
    )


def _empty_result() -> FundAnalytics:
    return FundAnalytics(
        return_1y_abs_pct=None,
        cagr_3y_pct=None,
        cagr_5y_pct=None,
        cagr_7y_pct=None,
        cagr_10y_pct=None,
        sd_pct=None,
        sharpe=None,
        sortino=None,
    )


def _round_or_none(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    return round(value, digits)
