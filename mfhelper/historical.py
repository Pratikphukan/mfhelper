"""Per-day historical drilldown: trailing-N-day metrics for a single fund.

Where the daily NAV scheduler appends one row per *run* and the analytics
report renders one row per *fund* (summary stats over multiple windows),
this module produces one row per *NAV-publish day* for a single fund --
useful for "show me the last 30 days of NAV / day-change / 52W / SMA /
RSI for fund X" drilldowns.

For each NAV-publish date in the requested window, we re-compute every
metric *as it would have been on that date*:

- ``nav`` -- the published NAV that day.
- ``day_change_pct`` -- vs. the prior NAV-publish day's NAV (from the
  same mfapi history; not the same calendar day).
- ``dist_52w_high_pct`` -- using the 365-day window ending at that date,
  via :func:`mfhelper.metrics.distance_from_52w_high`.
- ``dist_200d_sma_pct`` -- using the 200 NAV-publish days ending at that
  date, via :func:`mfhelper.metrics.distance_from_200d_sma`.
- ``rsi_14`` -- 14-day Wilder RSI as of that date, via
  :func:`mfhelper.metrics.rsi`. Each call seeds & smooths from the start
  of the available history, so the value matches what the daily-NAV
  scheduler would have written that day.

Any metric whose history requirement isn't met for a given date returns
``None`` (e.g. older days at the edge of a young fund's history don't
have 200 prior NAVs available -- those cells stay blank).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from mfhelper.mfapi import NavHistoryPoint
from mfhelper.metrics import (
    distance_from_200d_sma,
    distance_from_52w_high,
    rsi,
)


@dataclass(frozen=True)
class HistoricalRow:
    nav_date: date
    nav: float
    day_change_pct: float | None
    dist_52w_high_pct: float | None
    dist_200d_sma_pct: float | None
    rsi_14: float | None


def compute_historical_rows(
    history: list[NavHistoryPoint],
    *,
    days: int = 30,
) -> list[HistoricalRow]:
    """Produce one ``HistoricalRow`` per NAV-publish date in the trailing
    ``days`` window. Newest first.

    ``history`` is the full mfapi NAV history (newest-first as mfapi
    returns it; we sort defensively). We require the full history (not
    just the last ``days`` points) because each per-day metric needs to
    look back up to a year (52W) or 200 publish-days (SMA).

    If ``history`` has fewer than ``days`` entries, we return as many
    rows as exist.
    """
    if not history:
        return []
    if days < 1:
        raise ValueError("days must be >= 1")

    # Newest-first ordering of the full series.
    sorted_desc = sorted(history, key=lambda p: p.nav_date, reverse=True)

    # Take the trailing window's anchors (newest first), but pass the
    # FULL history into each metric call so the lookback windows have
    # enough data to be valid.
    window = sorted_desc[:days]

    out: list[HistoricalRow] = []
    for i, point in enumerate(window):
        # Day change vs. the prior NAV-publish day. We pull the prior
        # entry from ``sorted_desc`` (not just ``window``) so the very
        # first day in our window still gets a day-change figure when
        # the fund itself has earlier history.
        prior_point = (
            sorted_desc[i + 1] if i + 1 < len(sorted_desc) else None
        )
        day_change_pct = None
        if prior_point is not None and prior_point.nav > 0:
            day_change_pct = round(
                (point.nav - prior_point.nav) / prior_point.nav * 100.0, 4
            )

        dist_52w = distance_from_52w_high(
            history=sorted_desc,
            current_nav=point.nav,
            current_date=point.nav_date,
        )
        dist_200d = distance_from_200d_sma(
            history=sorted_desc,
            current_nav=point.nav,
            current_date=point.nav_date,
        )
        rsi_value = rsi(
            history=sorted_desc,
            current_nav=point.nav,
            current_date=point.nav_date,
        )

        out.append(HistoricalRow(
            nav_date=point.nav_date,
            nav=round(point.nav, 4),
            day_change_pct=day_change_pct,
            dist_52w_high_pct=dist_52w,
            dist_200d_sma_pct=dist_200d,
            rsi_14=rsi_value,
        ))

    return out
