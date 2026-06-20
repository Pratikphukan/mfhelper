"""Compute the full bouquet of return / risk metrics for a single fund.

This module is the calculation half of the per-fund JSON dump (the
writing half is :mod:`mfhelper.returns_writer`). Everything here is
deterministic, pure-Python, and operates on the NAV history that
:mod:`mfhelper.mfapi` already returns -- no extra data sources.

What gets computed (and the convention used):

- **Trailing returns** -- 1D, 1W, 1M, 3M, 6M, YTD, 1Y absolute, then
  CAGR for 2Y / 3Y / 5Y / 7Y / 10Y / since-inception. The under-1Y
  windows are *absolute*; multi-year windows are *CAGR*. This matches
  what every Indian factsheet you've ever seen reports.

- **Calendar-year returns** -- one entry per CY (e.g. ``2024_pct``),
  computed as ``NAV(Dec 31, year) / NAV(Dec 31, year-1) - 1``. The
  current calendar year is reported separately as
  ``current_year_ytd_pct``.

- **Financial-year returns** -- same idea but Apr 1 -> Mar 31 boundaries.
  Indian convention: FY26 is "Apr 2025 - Mar 2026".

- **Rolling returns** -- for windows 1Y/3Y/5Y/7Y, walk every NAV-publish
  day in history and compute the CAGR over the next ``window`` years.
  Report distribution stats: count, min/p25/median/p75/max, mean,
  ``pct_negative`` (how often this window finished underwater), and
  ``pct_above_12`` (how often it cleared the equity-fund rule-of-thumb
  12% mark). Daily stride; overlapping windows are intentional.

- **Risk** -- annualized SD of daily log returns over 3Y / 5Y / since
  inception, plus downside deviation (3Y) and a drawdown analysis
  (max drawdown peak/trough/recovery dates, duration, current drawdown).

- **Risk-adjusted** -- Sharpe / Sortino over 3Y and 5Y, Calmar over 3Y.
  Risk-free rate defaults to 7.0% (RBI repo proxy).

- **Extremes** -- best/worst day percentage and the dates, plus
  best/worst calendar-month percentage.

- **Hypothetical SIP XIRR** -- ₹10,000/month SIP on the 1st of each
  month, evaluated at 3Y / 5Y / 10Y horizons. Pure-Python bisection
  XIRR (no scipy dependency). Returns ``None`` for windows longer than
  the fund's available history.

Things explicitly NOT computed (and why) live in the ``unavailable``
section returned by :func:`compute_fund_returns` so the JSON file
self-documents the gaps.
"""

from __future__ import annotations

from datetime import date, timedelta
from math import sqrt
from typing import Iterable

from mfhelper.analytics import (
    DEFAULT_RISK_FREE_RATE_PCT,
    TRADING_DAYS_PER_YEAR,
    _absolute_return_pct as absolute_return_pct,
    _cagr_pct as cagr_pct,
    _daily_log_returns as daily_log_returns,
    _downside_deviation as downside_deviation,
    _nav_at_or_near as nav_at_or_near,
    _stdev as stdev,
)
from mfhelper.mfapi import NavHistoryPoint

# Tolerance (in days) for matching a target calendar date (e.g. Dec 31)
# to the nearest available NAV publish day. 7 covers any combination of
# weekends, public holidays, and the December last-Friday convention.
ANCHOR_TOLERANCE_DAYS = 7

# Default hypothetical-SIP parameters.
SIP_MONTHLY_AMOUNT_INR = 10_000
SIP_DAY_OF_MONTH = 1

# Rolling-return windows we report.
ROLLING_WINDOWS_YEARS = (1, 3, 5, 7)

# Minimum |day-over-day NAV change| that we treat as a "unit rebasement"
# rather than a legitimate market move. Indian equities have rarely moved
# more than 15% in a single day; even a 1:5 stock split is +400% on the
# split day. 50% is comfortably outside any plausible market move while
# still catching every kind of scheme-merger / unit-base reset we've seen
# from mfapi.in (Edelweiss Liquid had a +9903% one-day jump on 2017-07-01).
DISCONTINUITY_PCT_THRESHOLD = 50.0


# --- internal helpers ---------------------------------------------------------


def _nav_at_or_before(
    history: list[NavHistoryPoint], target: date,
) -> NavHistoryPoint | None:
    """Most recent NAV publish on or before ``target``. Used for
    calendar/financial-year boundaries and SIP buy dates -- we always
    want the *trading day* whose NAV would have been printed by EOD on
    or before the target date.
    """
    best: NavHistoryPoint | None = None
    for point in history:
        if point.nav_date <= target and (best is None or point.nav_date > best.nav_date):
            best = point
    return best


def _nav_at_or_after(
    history: list[NavHistoryPoint], target: date,
) -> NavHistoryPoint | None:
    """Earliest NAV publish on or after ``target``. Used for the
    hypothetical-SIP buy side: an investor placing an order on the 1st
    of the month gets units at the next available NAV publish."""
    best: NavHistoryPoint | None = None
    for point in history:
        if point.nav_date >= target and (best is None or point.nav_date < best.nav_date):
            best = point
    return best


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _detect_discontinuities(
    history: list[NavHistoryPoint],
) -> list[dict[str, object]]:
    """Find every consecutive day-over-day NAV jump exceeding the
    discontinuity threshold. These almost always indicate a unit-base
    rebasement (scheme merger, AMC takeover, plan-segregation history
    being stitched onto the wrong unit base) rather than a real market
    move."""
    chrono = sorted(history, key=lambda p: p.nav_date)
    out: list[dict[str, object]] = []
    for i in range(1, len(chrono)):
        prev, curr = chrono[i - 1], chrono[i]
        if prev.nav <= 0:
            continue
        pct = (curr.nav - prev.nav) / prev.nav * 100.0
        if abs(pct) > DISCONTINUITY_PCT_THRESHOLD:
            out.append({
                "prior_date": prev.nav_date.isoformat(),
                "prior_nav": round(prev.nav, 4),
                "after_date": curr.nav_date.isoformat(),
                "after_nav": round(curr.nav, 4),
                "jump_pct": round(pct, 2),
            })
    return out


def _trim_to_post_discontinuity(
    history: list[NavHistoryPoint],
) -> tuple[list[NavHistoryPoint], list[dict[str, object]]]:
    """If any discontinuities are present, drop all history prior to the
    most recent one (so the post-rebase NAV becomes the effective
    inception). Returns ``(trimmed_history, list_of_detected_jumps)``.
    The jump list is populated whether or not we actually trim, so the
    JSON file always self-documents data-quality findings.
    """
    chrono = sorted(history, key=lambda p: p.nav_date)
    discontinuities = _detect_discontinuities(chrono)
    if not discontinuities:
        return chrono, []

    last_after_iso = discontinuities[-1]["after_date"]
    assert isinstance(last_after_iso, str)
    last_after = date.fromisoformat(last_after_iso)
    trimmed = [p for p in chrono if p.nav_date >= last_after]
    return trimmed, discontinuities


# --- trailing returns ---------------------------------------------------------


def trailing_returns(
    history: list[NavHistoryPoint], as_of: date,
) -> dict[str, float | None]:
    """Trailing-window returns. <1Y are absolute, multi-year are CAGR."""
    chrono = sorted(history, key=lambda p: p.nav_date)
    if not chrono:
        return {}
    end_nav = chrono[-1].nav

    def absolute_for(days: int) -> float | None:
        anchor = nav_at_or_near(
            sorted(chrono, reverse=True, key=lambda p: p.nav_date),
            as_of - timedelta(days=days),
            tolerance_days=ANCHOR_TOLERANCE_DAYS,
        )
        if anchor is None:
            return None
        return absolute_return_pct(anchor.nav, end_nav)

    def cagr_for(years: int) -> float | None:
        target = as_of - timedelta(days=365 * years)
        anchor = nav_at_or_near(
            sorted(chrono, reverse=True, key=lambda p: p.nav_date),
            target,
            tolerance_days=ANCHOR_TOLERANCE_DAYS,
        )
        if anchor is None:
            return None
        elapsed_years = (as_of - anchor.nav_date).days / 365.0
        if elapsed_years <= 0:
            return None
        return cagr_pct(anchor.nav, end_nav, elapsed_years)

    # YTD: from Dec 31 of last calendar year (or the closest publish day on/before).
    ytd_anchor = _nav_at_or_before(chrono, date(as_of.year - 1, 12, 31))
    ytd_pct = absolute_return_pct(ytd_anchor.nav, end_nav) if ytd_anchor else None

    # Since inception.
    inception = chrono[0]
    elapsed_years = (as_of - inception.nav_date).days / 365.0
    si_pct: float | None = None
    if elapsed_years >= 1.0:
        si_pct = cagr_pct(inception.nav, end_nav, elapsed_years)
    elif elapsed_years > 0:
        si_pct = absolute_return_pct(inception.nav, end_nav)

    return {
        "1d_pct": _round(absolute_for(1)),
        "1w_pct": _round(absolute_for(7)),
        "1m_pct": _round(absolute_for(30)),
        "3m_pct": _round(absolute_for(91)),
        "6m_pct": _round(absolute_for(182)),
        "ytd_pct": _round(ytd_pct),
        "1y_absolute_pct": _round(absolute_for(365)),
        "2y_cagr_pct": _round(cagr_for(2)),
        "3y_cagr_pct": _round(cagr_for(3)),
        "5y_cagr_pct": _round(cagr_for(5)),
        "7y_cagr_pct": _round(cagr_for(7)),
        "10y_cagr_pct": _round(cagr_for(10)),
        "since_inception_cagr_pct": _round(si_pct),
        "since_inception_years": _round(elapsed_years, 2),
    }


# --- calendar / financial year returns ----------------------------------------


def calendar_year_returns(
    history: list[NavHistoryPoint], as_of: date,
) -> dict[str, float | None]:
    """Per-CY returns. ``NNNN_pct`` for completed years; ``current_year_ytd_pct``
    for the in-progress year."""
    chrono = sorted(history, key=lambda p: p.nav_date)
    if not chrono:
        return {}
    inception_year = chrono[0].nav_date.year
    out: dict[str, float | None] = {}
    for year in range(inception_year, as_of.year):
        start = _nav_at_or_before(chrono, date(year - 1, 12, 31))
        end = _nav_at_or_before(chrono, date(year, 12, 31))
        if start is None or end is None or start.nav_date >= end.nav_date:
            out[f"{year}_pct"] = None
        else:
            out[f"{year}_pct"] = _round(absolute_return_pct(start.nav, end.nav))

    # In-progress current year.
    cy_start = _nav_at_or_before(chrono, date(as_of.year - 1, 12, 31))
    if cy_start:
        out["current_year_ytd_pct"] = _round(
            absolute_return_pct(cy_start.nav, chrono[-1].nav)
        )
    else:
        out["current_year_ytd_pct"] = None
    return out


def financial_year_returns(
    history: list[NavHistoryPoint], as_of: date,
) -> dict[str, float | None]:
    """Per-FY returns. Indian FY runs Apr 1 -> Mar 31. ``FYxx`` is the
    year ending in March, e.g. ``FY26`` covers Apr 2025 -> Mar 2026."""
    chrono = sorted(history, key=lambda p: p.nav_date)
    if not chrono:
        return {}

    def fy_end_year_for(d: date) -> int:
        return d.year if d.month >= 4 else d.year - 1

    inception_fy_end = fy_end_year_for(chrono[0].nav_date) + 1
    current_fy_end = fy_end_year_for(as_of) + 1

    out: dict[str, float | None] = {}
    for fy_end_year in range(inception_fy_end, current_fy_end):
        start = _nav_at_or_before(chrono, date(fy_end_year - 1, 3, 31))
        end = _nav_at_or_before(chrono, date(fy_end_year, 3, 31))
        key = f"FY{fy_end_year % 100:02d}_pct"
        if start is None or end is None or start.nav_date >= end.nav_date:
            out[key] = None
        else:
            out[key] = _round(absolute_return_pct(start.nav, end.nav))

    # In-progress FY.
    fy_start = _nav_at_or_before(chrono, date(current_fy_end - 1, 3, 31))
    in_progress_key = f"FY{current_fy_end % 100:02d}_ytd_pct"
    if fy_start:
        out[in_progress_key] = _round(absolute_return_pct(fy_start.nav, chrono[-1].nav))
    else:
        out[in_progress_key] = None
    return out


# --- rolling returns ----------------------------------------------------------


def rolling_returns(
    history: list[NavHistoryPoint], as_of: date,
    *, windows_years: tuple[int, ...] = ROLLING_WINDOWS_YEARS,
) -> dict[str, dict[str, float | int | None] | None]:
    """For each rolling window, the distribution of CAGRs over all daily-strided
    overlapping windows that fit entirely within the fund's history."""
    chrono = sorted(history, key=lambda p: p.nav_date)
    if not chrono:
        return {}
    chrono_desc = sorted(history, reverse=True, key=lambda p: p.nav_date)

    out: dict[str, dict[str, float | int | None] | None] = {}
    for years in windows_years:
        values: list[float] = []
        offset = timedelta(days=365 * years)
        for start in chrono:
            target_end = start.nav_date + offset
            if target_end > as_of:
                break
            end = nav_at_or_near(
                chrono_desc, target_end, tolerance_days=ANCHOR_TOLERANCE_DAYS
            )
            if end is None or end.nav_date <= start.nav_date:
                continue
            elapsed_years = (end.nav_date - start.nav_date).days / 365.0
            v = cagr_pct(start.nav, end.nav, elapsed_years)
            if v is not None:
                values.append(v)

        key = f"{years}y_window"
        if not values:
            out[key] = None
            continue
        sv = sorted(values)
        n = len(sv)
        out[key] = {
            "samples": n,
            "min_pct": _round(sv[0]),
            "p25_pct": _round(sv[max(0, n // 4)]),
            "median_pct": _round(sv[n // 2]),
            "p75_pct": _round(sv[min(n - 1, (3 * n) // 4)]),
            "max_pct": _round(sv[-1]),
            "mean_pct": _round(sum(sv) / n),
            "pct_negative": _round(sum(1 for v in sv if v < 0) / n * 100.0),
            "pct_above_12": _round(sum(1 for v in sv if v >= 12.0) / n * 100.0),
        }
    return out


# --- drawdown / risk ----------------------------------------------------------


def _drawdown_analysis(history: list[NavHistoryPoint]) -> dict[str, object | None]:
    """Walk the chronological NAV series; track the running peak and find
    the largest peak-to-trough drop. Recovery date is the first date after
    the trough where NAV regains (or exceeds) the running peak that anchored
    the drawdown."""
    chrono = sorted(history, key=lambda p: p.nav_date)
    if not chrono:
        return {
            "max_drawdown_pct": None,
            "peak_date": None,
            "trough_date": None,
            "recovery_date": None,
            "duration_days": None,
            "current_drawdown_pct": None,
        }

    peak_nav = chrono[0].nav
    peak_date = chrono[0].nav_date
    max_dd_pct = 0.0
    max_dd_peak_nav = peak_nav
    max_dd_peak_date = peak_date
    max_dd_trough_date = peak_date

    for p in chrono:
        if p.nav > peak_nav:
            peak_nav = p.nav
            peak_date = p.nav_date
        if peak_nav <= 0:
            continue
        dd_pct = (p.nav - peak_nav) / peak_nav * 100.0
        if dd_pct < max_dd_pct:
            max_dd_pct = dd_pct
            max_dd_peak_nav = peak_nav
            max_dd_peak_date = peak_date
            max_dd_trough_date = p.nav_date

    recovery_date: date | None = None
    if max_dd_pct < 0:
        for p in chrono:
            if p.nav_date > max_dd_trough_date and p.nav >= max_dd_peak_nav:
                recovery_date = p.nav_date
                break

    duration_days: int | None = None
    if recovery_date is not None:
        duration_days = (recovery_date - max_dd_peak_date).days

    current_peak = max(p.nav for p in chrono)
    latest_nav = chrono[-1].nav
    current_dd_pct = (
        (latest_nav - current_peak) / current_peak * 100.0 if current_peak > 0 else 0.0
    )

    return {
        "max_drawdown_pct": _round(max_dd_pct),
        "peak_date": max_dd_peak_date.isoformat() if max_dd_pct < 0 else None,
        "trough_date": max_dd_trough_date.isoformat() if max_dd_pct < 0 else None,
        "recovery_date": recovery_date.isoformat() if recovery_date else None,
        "duration_days": duration_days,
        "current_drawdown_pct": _round(current_dd_pct),
    }


def risk_metrics(
    history: list[NavHistoryPoint], as_of: date,
) -> dict[str, object | None]:
    chrono = sorted(history, key=lambda p: p.nav_date)
    if not chrono:
        return {}

    def sd_over(days: int) -> float | None:
        cutoff = as_of - timedelta(days=days)
        window = [p for p in chrono if cutoff <= p.nav_date <= as_of]
        log_ret = daily_log_returns(window)
        s = stdev(log_ret)
        if s is None:
            return None
        return s * sqrt(TRADING_DAYS_PER_YEAR) * 100.0

    def downside_dev_over(days: int) -> float | None:
        cutoff = as_of - timedelta(days=days)
        window = [p for p in chrono if cutoff <= p.nav_date <= as_of]
        log_ret = daily_log_returns(window)
        d = downside_deviation(log_ret)
        if d is None:
            return None
        return d * sqrt(TRADING_DAYS_PER_YEAR) * 100.0

    si_log = daily_log_returns(chrono)
    si_sd = stdev(si_log)
    si_sd_pct = si_sd * sqrt(TRADING_DAYS_PER_YEAR) * 100.0 if si_sd else None

    out: dict[str, object | None] = {
        "sd_3y_annualized_pct": _round(sd_over(365 * 3)),
        "sd_5y_annualized_pct": _round(sd_over(365 * 5)),
        "sd_since_inception_annualized_pct": _round(si_sd_pct),
        "downside_deviation_3y_annualized_pct": _round(downside_dev_over(365 * 3)),
    }
    out.update(_drawdown_analysis(chrono))
    return out


# --- risk-adjusted ratios -----------------------------------------------------


def risk_adjusted(
    history: list[NavHistoryPoint], as_of: date,
    *, risk_free_rate_pct: float = DEFAULT_RISK_FREE_RATE_PCT,
) -> dict[str, object | None]:
    chrono = sorted(history, key=lambda p: p.nav_date)
    if not chrono:
        return {}

    def cagr_over(years: int) -> float | None:
        target = as_of - timedelta(days=365 * years)
        anchor = nav_at_or_near(
            sorted(chrono, reverse=True, key=lambda p: p.nav_date),
            target, tolerance_days=ANCHOR_TOLERANCE_DAYS,
        )
        if anchor is None or anchor.nav <= 0:
            return None
        elapsed_years = (as_of - anchor.nav_date).days / 365.0
        if elapsed_years <= 0:
            return None
        return cagr_pct(anchor.nav, chrono[-1].nav, elapsed_years)

    def sd_pct_over(days: int) -> float | None:
        cutoff = as_of - timedelta(days=days)
        window = [p for p in chrono if cutoff <= p.nav_date <= as_of]
        log_ret = daily_log_returns(window)
        s = stdev(log_ret)
        if s is None:
            return None
        return s * sqrt(TRADING_DAYS_PER_YEAR) * 100.0

    def dsd_pct_over(days: int) -> float | None:
        cutoff = as_of - timedelta(days=days)
        window = [p for p in chrono if cutoff <= p.nav_date <= as_of]
        log_ret = daily_log_returns(window)
        d = downside_deviation(log_ret)
        if d is None:
            return None
        return d * sqrt(TRADING_DAYS_PER_YEAR) * 100.0

    cagr_3y = cagr_over(3)
    cagr_5y = cagr_over(5)
    sd_3y = sd_pct_over(365 * 3)
    sd_5y = sd_pct_over(365 * 5)
    dsd_3y = dsd_pct_over(365 * 3)
    dsd_5y = dsd_pct_over(365 * 5)

    sharpe_3y: float | None = None
    if cagr_3y is not None and sd_3y and sd_3y > 0:
        sharpe_3y = (cagr_3y - risk_free_rate_pct) / sd_3y
    sharpe_5y: float | None = None
    if cagr_5y is not None and sd_5y and sd_5y > 0:
        sharpe_5y = (cagr_5y - risk_free_rate_pct) / sd_5y

    sortino_3y: float | None = None
    if cagr_3y is not None and dsd_3y and dsd_3y > 0:
        sortino_3y = (cagr_3y - risk_free_rate_pct) / dsd_3y
    sortino_5y: float | None = None
    if cagr_5y is not None and dsd_5y and dsd_5y > 0:
        sortino_5y = (cagr_5y - risk_free_rate_pct) / dsd_5y

    # Calmar = CAGR / |max drawdown over same window|
    dd = _drawdown_analysis([p for p in chrono if p.nav_date >= as_of - timedelta(days=365 * 3)])
    calmar_3y: float | None = None
    if cagr_3y is not None and dd.get("max_drawdown_pct") is not None:
        max_dd = dd["max_drawdown_pct"]
        assert isinstance(max_dd, (int, float))
        if max_dd < 0:
            calmar_3y = cagr_3y / abs(max_dd)

    return {
        "rfr_assumption_pct": risk_free_rate_pct,
        "sharpe_3y": _round(sharpe_3y),
        "sharpe_5y": _round(sharpe_5y),
        "sortino_3y": _round(sortino_3y),
        "sortino_5y": _round(sortino_5y),
        "calmar_3y": _round(calmar_3y),
    }


# --- extremes -----------------------------------------------------------------


def extremes(history: list[NavHistoryPoint]) -> dict[str, object | None]:
    """Best/worst single day and best/worst calendar-month return."""
    chrono = sorted(history, key=lambda p: p.nav_date)
    if len(chrono) < 2:
        return {}

    # Daily extremes.
    best_day_pct = None
    best_day_date = None
    worst_day_pct = None
    worst_day_date = None
    prev = chrono[0]
    for p in chrono[1:]:
        if prev.nav > 0:
            pct = (p.nav - prev.nav) / prev.nav * 100.0
            if best_day_pct is None or pct > best_day_pct:
                best_day_pct = pct
                best_day_date = p.nav_date
            if worst_day_pct is None or pct < worst_day_pct:
                worst_day_pct = pct
                worst_day_date = p.nav_date
        prev = p

    # Monthly extremes: group end-of-month NAVs, compute month-over-month %.
    by_month: dict[tuple[int, int], NavHistoryPoint] = {}
    for p in chrono:
        key = (p.nav_date.year, p.nav_date.month)
        # Last NAV of each month wins.
        existing = by_month.get(key)
        if existing is None or p.nav_date > existing.nav_date:
            by_month[key] = p
    months_sorted = sorted(by_month.items())
    best_month_pct = worst_month_pct = None
    best_month_period = worst_month_period = None
    for i in range(1, len(months_sorted)):
        prev_key, prev_p = months_sorted[i - 1]
        curr_key, curr_p = months_sorted[i]
        if prev_p.nav <= 0:
            continue
        pct = (curr_p.nav - prev_p.nav) / prev_p.nav * 100.0
        period = f"{curr_key[0]:04d}-{curr_key[1]:02d}"
        if best_month_pct is None or pct > best_month_pct:
            best_month_pct = pct
            best_month_period = period
        if worst_month_pct is None or pct < worst_month_pct:
            worst_month_pct = pct
            worst_month_period = period

    return {
        "best_day_pct": _round(best_day_pct),
        "best_day_date": best_day_date.isoformat() if best_day_date else None,
        "worst_day_pct": _round(worst_day_pct),
        "worst_day_date": worst_day_date.isoformat() if worst_day_date else None,
        "best_month_pct": _round(best_month_pct),
        "best_month_period": best_month_period,
        "worst_month_pct": _round(worst_month_pct),
        "worst_month_period": worst_month_period,
    }


# --- hypothetical SIP XIRR ----------------------------------------------------


def _xirr_pct(cash_flows: list[tuple[date, float]]) -> float | None:
    """IRR for irregular cash flows, returned as annual percent.

    Uses bisection on ``[-0.999, 10.0]`` (i.e. -99.9% to +1000% annualized).
    Returns ``None`` if the bracket doesn't contain a sign change (in
    practice: all-positive or all-negative cash flows; not a real IRR).
    """
    if len(cash_flows) < 2:
        return None
    base = cash_flows[0][0]

    def npv(rate: float) -> float:
        total = 0.0
        for d, cf in cash_flows:
            years = (d - base).days / 365.0
            total += cf / ((1.0 + rate) ** years)
        return total

    lo, hi = -0.999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(120):
        mid = (lo + hi) / 2.0
        f_mid = npv(mid)
        if abs(f_mid) < 1e-7 or (hi - lo) < 1e-10:
            return mid * 100.0
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return mid * 100.0


def hypothetical_sip_xirr(
    history: list[NavHistoryPoint], as_of: date,
    *,
    monthly_amount_inr: int = SIP_MONTHLY_AMOUNT_INR,
    day_of_month: int = SIP_DAY_OF_MONTH,
    horizons_years: tuple[int, ...] = (3, 5, 10),
) -> dict[str, object | None]:
    """SIP simulation: for each horizon, place a monthly buy on
    ``day_of_month`` and solve XIRR over the resulting cash flow stream.
    Skips horizons longer than the fund's available history."""
    chrono = sorted(history, key=lambda p: p.nav_date)
    if not chrono:
        return {}
    inception = chrono[0].nav_date
    end_nav = chrono[-1].nav

    out: dict[str, object | None] = {
        "monthly_amount_inr": monthly_amount_inr,
        "day_of_month": day_of_month,
    }

    for years in horizons_years:
        start = as_of - timedelta(days=365 * years)
        if start < inception:
            out[f"{years}y_xirr_pct"] = None
            continue

        cash_flows: list[tuple[date, float]] = []
        total_units = 0.0
        # Iterate month-by-month from start month to as_of month.
        cursor = date(start.year, start.month, 1)
        end_month = date(as_of.year, as_of.month, 1)
        while cursor <= end_month:
            try:
                buy_target = cursor.replace(day=day_of_month)
            except ValueError:
                buy_target = cursor  # fall back to first of month
            if buy_target > as_of:
                break
            buy = _nav_at_or_after(chrono, buy_target)
            if buy is None or buy.nav_date > as_of:
                # No NAV available before as_of -> end of usable buys
                break
            cash_flows.append((buy.nav_date, -float(monthly_amount_inr)))
            total_units += monthly_amount_inr / buy.nav

            # Advance one month.
            if cursor.month == 12:
                cursor = date(cursor.year + 1, 1, 1)
            else:
                cursor = date(cursor.year, cursor.month + 1, 1)

        if not cash_flows:
            out[f"{years}y_xirr_pct"] = None
            continue
        cash_flows.append((as_of, total_units * end_nav))
        out[f"{years}y_xirr_pct"] = _round(_xirr_pct(cash_flows))

    return out


# --- top-level orchestrator ---------------------------------------------------


def compute_fund_returns(
    history: Iterable[NavHistoryPoint], *,
    as_of: date | None = None,
    risk_free_rate_pct: float = DEFAULT_RISK_FREE_RATE_PCT,
) -> dict[str, object]:
    """Bundle all sections into a single structured dict suitable for JSON.

    Detects and auto-trims unit-base discontinuities (jumps >50% day-over-
    day) before computing anything. Without this, funds that have ever
    been re-based (e.g. via AMC merger) would emit a meaningless
    since-inception CAGR. The detected discontinuities are still surfaced
    in the ``data_quality`` block of the output so the trim is auditable.
    """
    history_list = list(history)
    empty_data_quality = {
        "discontinuities_detected": [],
        "trimmed_to_after": None,
        "note": (
            "No NAV jumps > 50% day-over-day detected. Full mfapi.in "
            "history used for all metrics."
        ),
    }
    if not history_list:
        return {
            "history": None,
            "data_quality": empty_data_quality,
            "trailing_returns": {},
            "calendar_year_returns": {},
            "financial_year_returns": {},
            "rolling_returns": {},
            "risk": {},
            "risk_adjusted": {},
            "extremes": {},
            "hypothetical_sip_xirr": {},
        }

    raw_chrono = sorted(history_list, key=lambda p: p.nav_date)
    cleaned, discontinuities = _trim_to_post_discontinuity(raw_chrono)
    if not cleaned:
        # Should never happen because the post-rebase point is always kept,
        # but be defensive.
        cleaned = raw_chrono

    latest = cleaned[-1]
    if as_of is None:
        as_of = latest.nav_date

    if discontinuities:
        last_after_iso = discontinuities[-1]["after_date"]
        data_quality: dict[str, object] = {
            "discontinuities_detected": discontinuities,
            "trimmed_to_after": last_after_iso,
            "note": (
                "Detected one or more day-over-day NAV jumps > 50%, which "
                "almost always indicate a unit-base rebasement (scheme "
                "merger / AMC takeover / plan-segregation stitched onto a "
                "different unit base) rather than a real market move. "
                "Pre-rebase history was excluded from all calculations to "
                "prevent a polluted since-inception CAGR. The dropped "
                "events are listed above for auditing."
            ),
        }
    else:
        data_quality = empty_data_quality

    return {
        "history": {
            "first_nav_date": cleaned[0].nav_date.isoformat(),
            "latest_nav_date": latest.nav_date.isoformat(),
            "latest_nav": _round(latest.nav, 4),
            "total_publish_days": len(cleaned),
            "raw_total_publish_days": len(raw_chrono),
            "as_of": as_of.isoformat(),
        },
        "data_quality": data_quality,
        "trailing_returns": trailing_returns(cleaned, as_of),
        "calendar_year_returns": calendar_year_returns(cleaned, as_of),
        "financial_year_returns": financial_year_returns(cleaned, as_of),
        "rolling_returns": rolling_returns(cleaned, as_of),
        "risk": risk_metrics(cleaned, as_of),
        "risk_adjusted": risk_adjusted(
            cleaned, as_of, risk_free_rate_pct=risk_free_rate_pct,
        ),
        "extremes": extremes(cleaned),
        "hypothetical_sip_xirr": hypothetical_sip_xirr(cleaned, as_of),
    }


def unavailable_metrics() -> dict[str, str]:
    """Honest disclosure of metrics we COULD compute given more data --
    embedded in every JSON file so the gaps self-document."""
    return {
        "real_return_pct": (
            "Inflation-adjusted CAGR. Needs an India CPI series; the World "
            "Bank Open Data API provides annual CPI without auth."
        ),
        "after_tax_return_pct": (
            "Post-LTCG/STCG return. Needs a per-fund category tag in "
            "funds.yaml (equity / debt / hybrid / international FoF) plus "
            "the Indian capital-gains rules (deterministic in code)."
        ),
        "active_return_vs_benchmark_pct": (
            "Fund return - benchmark return. Needs benchmark-index history "
            "(NSE Indices CSV at niftyindices.com or yfinance)."
        ),
        "alpha": (
            "Jensen's alpha (excess return after controlling for beta). "
            "Same data dependency as active return, plus a beta computation "
            "against the benchmark."
        ),
        "actual_xirr_pct": (
            "True money-weighted return based on YOUR transactions. Needs "
            "the broker's transaction history (e.g. Groww trading API)."
        ),
    }
