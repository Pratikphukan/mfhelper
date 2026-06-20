"""Compute fund-vs-benchmark comparison metrics.

This module turns a fund's NAV history and a benchmark's index-close
history into a structured "vs benchmark" dict suitable for embedding
into the per-fund returns JSON. The logic is built deliberately on top
of :mod:`mfhelper.returns_calc` so that:

- Trailing returns and rolling-CAGR distributions for the benchmark are
  computed by exactly the same code paths that produce the fund's
  numbers (no separate quirks).
- Active return / beat-rate / information ratio are derived from
  per-window CAGR pairs (one fund value, one benchmark value, on the
  same start date and same end date), not from independently-computed
  numbers -- which is the only way to get a defensible alpha.

What gets computed (per fund-benchmark pair):

- ``trailing_active_returns``: fund_trailing - benchmark_trailing for
  every standard window (1Y / 3Y / 5Y / 7Y / 10Y / since-inception).
- ``rolling_active_returns``: for every rolling window (1Y / 3Y / 5Y /
  7Y), the distribution of *paired* (fund_CAGR - benchmark_CAGR)
  values, plus a beat-rate (% of windows where fund > benchmark).
- ``information_ratio_*``: active return divided by tracking error
  (annualized SD of the daily fund-vs-benchmark log-return delta)
  over 3Y and 5Y windows. The standard "skill per unit of deviation
  from benchmark" measure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from math import sqrt
from typing import Sequence

from mfhelper.benchmarks import BenchmarkPoint
from mfhelper.mfapi import NavHistoryPoint
from mfhelper.returns_calc import (
    ANCHOR_TOLERANCE_DAYS,
    DEFAULT_RISK_FREE_RATE_PCT,  # noqa: F401  (re-exported for symmetry)
    ROLLING_WINDOWS_YEARS,
    _round,
    cagr_pct,
    daily_log_returns,
    nav_at_or_near,
    rolling_returns,
    stdev,
    trailing_returns,
)

log = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252


# ----------------------------------------------------------------------------
# Adapters: BenchmarkPoint <-> NavHistoryPoint
#
# Reusing returns_calc means treating an index-close series like a NAV
# series. The underlying math (CAGR over a window, rolling distribution,
# trailing returns) doesn't care whether a "level" is a mutual fund's NAV
# or a stock index's value -- both are non-negative time-series whose
# point-to-point ratios give returns. The adapter just relabels the
# fields.
# ----------------------------------------------------------------------------


def _benchmark_to_navlike(history: Sequence[BenchmarkPoint]) -> list[NavHistoryPoint]:
    return [NavHistoryPoint(nav_date=p.date, nav=p.close) for p in history]


# ----------------------------------------------------------------------------
# Pair computation: same start, same end, both series.
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class _PairedCagr:
    start_date: date
    end_date: date
    fund_cagr_pct: float
    benchmark_cagr_pct: float

    @property
    def active_return_pct(self) -> float:
        return self.fund_cagr_pct - self.benchmark_cagr_pct


def _paired_rolling(
    fund: list[NavHistoryPoint],
    bench: list[NavHistoryPoint],
    *, years: int, as_of: date,
) -> list[_PairedCagr]:
    """For every fund start-date that fits, compute fund and benchmark
    CAGR over the same window and pair them. We anchor both endpoints to
    the FUND's calendar, then snap the benchmark to its closest available
    publish day within :data:`ANCHOR_TOLERANCE_DAYS`. This way the same
    week-end / holiday treatment applies to both, so the active-return
    distribution isn't biased by mismatched calendars."""
    if not fund or not bench:
        return []
    fund_chrono = sorted(fund, key=lambda p: p.nav_date)
    bench_desc = sorted(bench, reverse=True, key=lambda p: p.nav_date)
    fund_desc = sorted(fund, reverse=True, key=lambda p: p.nav_date)
    bench_first = min(p.nav_date for p in bench)

    out: list[_PairedCagr] = []
    offset = timedelta(days=365 * years)
    for start in fund_chrono:
        if start.nav_date < bench_first:
            # No benchmark data on or before this start -> can't pair.
            continue
        target_end = start.nav_date + offset
        if target_end > as_of:
            break

        # Snap end (and start) to nearest available publish day on each
        # side. ANCHOR_TOLERANCE_DAYS is generous enough to cover any
        # weekend/holiday pair across the two calendars.
        bench_start = nav_at_or_near(
            bench_desc, start.nav_date, tolerance_days=ANCHOR_TOLERANCE_DAYS,
        )
        if bench_start is None or bench_start.nav <= 0:
            continue
        fund_end = nav_at_or_near(
            fund_desc, target_end, tolerance_days=ANCHOR_TOLERANCE_DAYS,
        )
        if fund_end is None or fund_end.nav_date <= start.nav_date:
            continue
        bench_end = nav_at_or_near(
            bench_desc, target_end, tolerance_days=ANCHOR_TOLERANCE_DAYS,
        )
        if bench_end is None or bench_end.nav_date <= bench_start.nav_date:
            continue

        # Use the FUND's elapsed years for both, so the per-year rate is
        # over the same denominator. (The benchmark snap may differ by a
        # day; that's fine -- it's already corrected for via the
        # tolerance-based matching.)
        elapsed_years = (fund_end.nav_date - start.nav_date).days / 365.0
        if elapsed_years <= 0:
            continue
        fund_cagr = cagr_pct(start.nav, fund_end.nav, elapsed_years)
        bench_cagr = cagr_pct(bench_start.nav, bench_end.nav, elapsed_years)
        if fund_cagr is None or bench_cagr is None:
            continue
        out.append(_PairedCagr(
            start_date=start.nav_date,
            end_date=fund_end.nav_date,
            fund_cagr_pct=fund_cagr,
            benchmark_cagr_pct=bench_cagr,
        ))
    return out


def _distribution_summary(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {}
    sv = sorted(values)
    n = len(sv)
    return {
        "samples": n,
        "min_pct": _round(sv[0]),
        "p25_pct": _round(sv[max(0, n // 4)]),
        "median_pct": _round(sv[n // 2]),
        "p75_pct": _round(sv[min(n - 1, (3 * n) // 4)]),
        "max_pct": _round(sv[-1]),
        "mean_pct": _round(sum(sv) / n),
    }


def _paired_trailing_active(
    fund: list[NavHistoryPoint],
    bench: list[NavHistoryPoint],
    as_of: date,
) -> dict[str, float | None]:
    """For each trailing window, fund_return - benchmark_return.

    Both are computed by :func:`mfhelper.returns_calc.trailing_returns`,
    which means the under-1Y windows are absolute (raw growth) and the
    multi-year windows are CAGR -- and we subtract within each pair, so
    the apples-to-apples convention is preserved naturally."""
    fund_trail = trailing_returns(fund, as_of)
    bench_trail = trailing_returns(bench, as_of)
    keys = (
        "1y_absolute_pct",
        "2y_cagr_pct",
        "3y_cagr_pct",
        "5y_cagr_pct",
        "7y_cagr_pct",
        "10y_cagr_pct",
        "since_inception_cagr_pct",
    )
    out: dict[str, float | None] = {}
    for k in keys:
        f = fund_trail.get(k)
        b = bench_trail.get(k)
        out[k] = (
            _round(f - b) if isinstance(f, (int, float)) and isinstance(b, (int, float))
            else None
        )
    return out


def _information_ratio(
    fund: list[NavHistoryPoint],
    bench: list[NavHistoryPoint],
    *, as_of: date, years: int,
) -> dict[str, object | None]:
    """Information ratio = active CAGR / tracking error (annualized SD of
    daily fund-bench log-return delta)."""
    cutoff = as_of - timedelta(days=365 * years)
    fund_window = [p for p in fund if cutoff <= p.nav_date <= as_of]
    bench_window = [p for p in bench if cutoff <= p.nav_date <= as_of]
    if len(fund_window) < 30 or len(bench_window) < 30:
        return {"active_cagr_pct": None, "tracking_error_pct": None, "info_ratio": None}

    fund_log = daily_log_returns(fund_window)
    bench_log = daily_log_returns(bench_window)

    # Pair daily log-returns by date. We rebuild date-keyed lookups so we
    # can intersect on common dates without depending on ordering.
    fund_chrono = sorted(fund_window, key=lambda p: p.nav_date)
    bench_chrono = sorted(bench_window, key=lambda p: p.nav_date)
    fund_pairs: dict[date, float] = {}
    prev = fund_chrono[0]
    for p in fund_chrono[1:]:
        if prev.nav > 0 and p.nav > 0:
            from math import log as _ln
            fund_pairs[p.nav_date] = _ln(p.nav / prev.nav)
        prev = p
    bench_pairs: dict[date, float] = {}
    prev = bench_chrono[0]
    for p in bench_chrono[1:]:
        if prev.nav > 0 and p.nav > 0:
            from math import log as _ln
            bench_pairs[p.nav_date] = _ln(p.nav / prev.nav)
        prev = p
    common = sorted(set(fund_pairs.keys()) & set(bench_pairs.keys()))
    if len(common) < 30:
        return {"active_cagr_pct": None, "tracking_error_pct": None, "info_ratio": None}
    deltas = [fund_pairs[d] - bench_pairs[d] for d in common]

    te_daily = stdev(deltas)
    te_annual_pct = (
        te_daily * sqrt(TRADING_DAYS_PER_YEAR) * 100.0
        if te_daily is not None else None
    )

    # Active CAGR over the same window: anchor at start, end at as_of.
    fund_anchor = nav_at_or_near(
        sorted(fund, reverse=True, key=lambda p: p.nav_date),
        as_of - timedelta(days=365 * years),
        tolerance_days=ANCHOR_TOLERANCE_DAYS,
    )
    bench_anchor = nav_at_or_near(
        sorted(bench, reverse=True, key=lambda p: p.nav_date),
        as_of - timedelta(days=365 * years),
        tolerance_days=ANCHOR_TOLERANCE_DAYS,
    )
    fund_end = sorted(fund, key=lambda p: p.nav_date)[-1]
    bench_end = sorted(bench, key=lambda p: p.nav_date)[-1]
    if (
        fund_anchor is None or bench_anchor is None
        or fund_anchor.nav <= 0 or bench_anchor.nav <= 0
    ):
        return {"active_cagr_pct": None, "tracking_error_pct": _round(te_annual_pct), "info_ratio": None}
    elapsed = (as_of - fund_anchor.nav_date).days / 365.0
    if elapsed <= 0:
        return {"active_cagr_pct": None, "tracking_error_pct": _round(te_annual_pct), "info_ratio": None}
    fund_cagr = cagr_pct(fund_anchor.nav, fund_end.nav, elapsed)
    bench_cagr = cagr_pct(bench_anchor.nav, bench_end.nav, elapsed)
    if fund_cagr is None or bench_cagr is None:
        return {"active_cagr_pct": None, "tracking_error_pct": _round(te_annual_pct), "info_ratio": None}
    active = fund_cagr - bench_cagr

    info_ratio = (
        active / te_annual_pct
        if te_annual_pct and te_annual_pct > 0 else None
    )
    return {
        "active_cagr_pct": _round(active),
        "tracking_error_pct": _round(te_annual_pct),
        "info_ratio": _round(info_ratio) if info_ratio is not None else None,
    }


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------


def compute_vs_benchmark(
    fund_history: Sequence[NavHistoryPoint],
    benchmark_history: Sequence[BenchmarkPoint],
    *,
    benchmark_name: str,
    variant: str,
    benchmark_note: str | None = None,
    as_of: date | None = None,
    windows_years: tuple[int, ...] = ROLLING_WINDOWS_YEARS,
) -> dict[str, object]:
    fund = sorted(fund_history, key=lambda p: p.nav_date)
    bench = sorted(_benchmark_to_navlike(benchmark_history), key=lambda p: p.nav_date)
    if not fund or not bench:
        return {
            "benchmark_name": benchmark_name,
            "variant": variant,
            "data_quality": {
                "note": "Fund or benchmark history was empty -- no comparison computed.",
            },
        }

    if as_of is None:
        as_of = fund[-1].nav_date

    # The comparison only meaningfully starts when BOTH series exist.
    earliest_common = max(fund[0].nav_date, bench[0].nav_date)
    fund_for_compare = [p for p in fund if p.nav_date >= earliest_common]
    bench_for_compare = [p for p in bench if p.nav_date >= earliest_common]

    # Benchmark, viewed through the same metric machinery as the fund.
    bench_trail = trailing_returns(bench_for_compare, as_of)
    bench_rolling = rolling_returns(
        bench_for_compare, as_of, windows_years=windows_years,
    )

    # Active returns: fund - benchmark, paired per window.
    rolling_active: dict[str, dict[str, float | int] | None] = {}
    beat_rates: dict[str, float | None] = {}
    for years in windows_years:
        pairs = _paired_rolling(
            fund_for_compare, bench_for_compare, years=years, as_of=as_of,
        )
        key = f"{years}y_window"
        if not pairs:
            rolling_active[key] = None
            beat_rates[key] = None
            continue
        active_values = [pp.active_return_pct for pp in pairs]
        summary = _distribution_summary(active_values)
        # Augment with directional stats specific to "vs benchmark".
        summary["pct_fund_beat_benchmark"] = _round(
            sum(1 for v in active_values if v > 0) / len(active_values) * 100.0
        )
        summary["pct_fund_beat_by_3"] = _round(
            sum(1 for v in active_values if v > 3.0) / len(active_values) * 100.0
        )
        summary["pct_fund_underperformed_by_3"] = _round(
            sum(1 for v in active_values if v < -3.0) / len(active_values) * 100.0
        )
        rolling_active[key] = summary
        beat_rates[key] = summary["pct_fund_beat_benchmark"]

    # Information ratio at 3Y and 5Y.
    ir_3y = _information_ratio(
        fund_for_compare, bench_for_compare, as_of=as_of, years=3,
    )
    ir_5y = _information_ratio(
        fund_for_compare, bench_for_compare, as_of=as_of, years=5,
    )

    return {
        "benchmark_name": benchmark_name,
        "variant": variant,
        "history": {
            "first_date": bench[0].nav_date.isoformat(),
            "latest_date": bench[-1].nav_date.isoformat(),
            "earliest_common_date": earliest_common.isoformat(),
            "total_publish_days": len(bench),
            "data_source": "niftyindices.com",
        },
        "trailing_returns": bench_trail,
        "rolling_returns": bench_rolling,
        "trailing_active_returns": _paired_trailing_active(
            fund_for_compare, bench_for_compare, as_of,
        ),
        "rolling_active_returns": rolling_active,
        "beat_rate_pct": beat_rates,
        "information_ratio_3y": ir_3y,
        "information_ratio_5y": ir_5y,
        "data_quality": {
            "variant_used": variant,
            "note": benchmark_note or (
                "PR (price-return) data: dividends paid by index "
                "constituents are NOT reinvested in the benchmark. The "
                "fully-fair comparison would use TRI (Total Return Index), "
                "which would lift the benchmark by roughly the index "
                "dividend yield (~1-1.5%/yr). Active-return numbers are "
                "thus overstated by that amount; the *shape* of the "
                "rolling distribution and beat-rate is unchanged."
                if variant == "PR"
                else None
            ),
        },
    }
