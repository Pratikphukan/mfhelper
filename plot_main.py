"""Generate per-fund rolling-return PNGs (one image per fund).

Each output is a multi-panel chart at ``data/fund_plots/{code}.png``
combining three views of rolling returns:

  Top panel    — TIME SERIES of rolling 3Y CAGR over time (x = window
                  start date, y = annualized return for that window).
                  When a benchmark is configured for the fund, the
                  benchmark's same-window rolling CAGR is overlaid as
                  a dashed line, making "is the fund actually adding
                  value, or just riding the market?" visible at a
                  glance.

  Middle panel — HISTOGRAM of rolling-CAGR distributions, one
                  sub-histogram per window length (1Y / 3Y / 5Y / 7Y).
                  Shows the SHAPE of returns: long tails, clustering,
                  skew. With a benchmark, the benchmark distribution
                  is overlaid in a translucent second colour.

  Bottom panel — BOX PLOT comparing all four window-length
                  distributions side-by-side. Shows how the spread
                  TIGHTENS as the window grows (the equity-time-horizon
                  principle). With a benchmark, paired boxes per window.

Why a separate CLI: rolling-window computation over a fund's full
history is fast (~1s) but takes 8+ MB of plot memory; we don't want it
in the daily scheduler path. Run it whenever you want fresh visuals.

Usage:

    .venv/bin/python plot_main.py                       # all funds
    .venv/bin/python plot_main.py --code 120492         # one fund
    .venv/bin/python plot_main.py --code 120492 --code 127042
    .venv/bin/python plot_main.py --no-benchmark         # skip overlay
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.figure import Figure

from mfhelper.benchmarks import BenchmarkHistory, fetch_benchmark_history
from mfhelper.config import load_funds
from mfhelper.mfapi import NavHistoryPoint, fetch_history
from mfhelper.returns_calc import (
    ANCHOR_TOLERANCE_DAYS,
    ROLLING_WINDOWS_YEARS,
    cagr_pct,
    nav_at_or_near,
)

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
DEFAULT_FUNDS_PATH = CONFIG_DIR / "funds.yaml"
BENCHMARKS_PATH = CONFIG_DIR / "benchmarks.yaml"
DEFAULT_OUTPUT_DIR = DATA_DIR / "fund_plots"
BENCHMARK_CACHE_DIR = DATA_DIR / "benchmark_history"

# Visual constants. Kept tweakable in one place.
FUND_COLOR = "#1f4e79"          # deep blue
BENCH_COLOR = "#bf6c0a"         # warm amber for clear contrast
EQUITY_THRESHOLD_COLOR = "#888888"  # gray dotted reference
EQUITY_THRESHOLD_PCT = 12.0     # the rule-of-thumb "equities should beat this"
WINDOW_COLORS = ("#80bcd1", "#1f4e79", "#264653", "#000000")  # light->dark for 1/3/5/7Y


def _configure_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / "mfhelper_plot.log"
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    for handler in list(root.handlers):
        root.removeHandler(handler)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(fmt)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)


def _load_benchmark_map(path: Path) -> dict[str, dict[str, str | None]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    out: dict[str, dict[str, str | None]] = {}
    for entry in raw.get("benchmarks") or []:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("code") or "").strip()
        index_name = str(entry.get("index_name") or "").strip()
        if not code or not index_name:
            continue
        out[code] = {
            "index_name": index_name,
            "variant": str(entry.get("variant") or "PR").strip(),
        }
    return out


def _benchmark_to_navlike(history) -> list[NavHistoryPoint]:
    return [NavHistoryPoint(nav_date=p.date, nav=p.close) for p in history]


def _rolling_cagr_series(
    history: list[NavHistoryPoint], *, years: int, as_of: date,
) -> tuple[list[date], list[float]]:
    """For each chronological start point, return (start_date, CAGR%) over
    the next `years`. Stops when the window would extend past as_of.
    Mirrors the logic in returns_calc.rolling_returns but exposes the
    full series instead of just the distribution summary."""
    chrono = sorted(history, key=lambda p: p.nav_date)
    chrono_desc = sorted(history, reverse=True, key=lambda p: p.nav_date)
    offset = timedelta(days=365 * years)
    dates: list[date] = []
    values: list[float] = []
    for start in chrono:
        target_end = start.nav_date + offset
        if target_end > as_of:
            break
        end = nav_at_or_near(
            chrono_desc, target_end, tolerance_days=ANCHOR_TOLERANCE_DAYS,
        )
        if end is None or end.nav_date <= start.nav_date:
            continue
        elapsed_years = (end.nav_date - start.nav_date).days / 365.0
        v = cagr_pct(start.nav, end.nav, elapsed_years)
        if v is None:
            continue
        dates.append(start.nav_date)
        values.append(v)
    return dates, values


def _draw_time_series(
    ax,
    fund_dates: list[date], fund_values: list[float],
    *,
    bench_dates: list[date] | None, bench_values: list[float] | None,
    fund_label: str, bench_label: str | None,
    window_years: int,
) -> None:
    ax.plot(
        fund_dates, fund_values,
        color=FUND_COLOR, linewidth=2.0, label=fund_label,
    )
    if bench_dates and bench_values:
        ax.plot(
            bench_dates, bench_values,
            color=BENCH_COLOR, linewidth=1.6, linestyle="--",
            label=bench_label or "Benchmark",
        )
    ax.axhline(
        EQUITY_THRESHOLD_PCT,
        color=EQUITY_THRESHOLD_COLOR, linestyle=":", linewidth=1.0,
    )
    ax.text(
        ax.get_xlim()[1], EQUITY_THRESHOLD_PCT,
        f" {EQUITY_THRESHOLD_PCT:.0f}% rule-of-thumb",
        color=EQUITY_THRESHOLD_COLOR, fontsize=8, va="center",
    )
    ax.set_title(
        f"Rolling {window_years}-year CAGR over time  "
        f"(x = window START date; line value = annualized return for the "
        f"{window_years}Y window starting that day)",
        fontsize=10,
    )
    ax.set_ylabel("CAGR (%)")
    ax.grid(True, alpha=0.3)
    # Legend pinned to the bottom-left so it doesn't fight with the
    # title; for funds whose rolling 3Y briefly went negative around the
    # 2020 crash, the bottom-left corner is also where the data is
    # least dense.
    ax.legend(loc="lower left", fontsize=9, framealpha=0.85)
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))


def _draw_histograms(
    axes,
    series_per_window: dict[int, tuple[list[float], list[float] | None]],
    *,
    fund_label: str, bench_label: str | None,
) -> None:
    """One sub-axis per window. Fund hist is solid; benchmark (if any)
    overlaid translucent."""
    for ax, years in zip(axes, ROLLING_WINDOWS_YEARS):
        fund_vals, bench_vals = series_per_window.get(years, ([], None))
        if not fund_vals:
            ax.set_axis_off()
            continue
        all_vals = list(fund_vals)
        if bench_vals:
            all_vals.extend(bench_vals)

        # Clip x-axis to the central 99% of the distribution. Without this,
        # the COVID-era 1Y windows (which can swing from -35% to +90%)
        # stretch the axis so wide that the bulk of the distribution
        # squashes into a few invisible bins. We still INCLUDE the outliers
        # in the histogram count -- they get clipped into the leftmost /
        # rightmost bins -- they just don't dominate the visual scale.
        sv = sorted(all_vals)
        n = len(sv)
        lo = sv[max(0, int(n * 0.005))]
        hi = sv[min(n - 1, int(n * 0.995))]
        # Add ~5% padding either side, and cap at the actual extremes.
        span = max(hi - lo, 1.0)
        x_lo = max(sv[0], lo - 0.05 * span)
        x_hi = min(sv[-1], hi + 0.05 * span)

        bin_edges = 30
        ax.hist(
            fund_vals, bins=bin_edges, range=(x_lo, x_hi),
            color=FUND_COLOR, alpha=0.65,
            edgecolor="white", linewidth=0.4, label=fund_label,
        )
        if bench_vals:
            ax.hist(
                bench_vals, bins=bin_edges, range=(x_lo, x_hi),
                color=BENCH_COLOR, alpha=0.45,
                edgecolor="white", linewidth=0.4,
                label=bench_label or "Benchmark",
            )
        ax.axvline(0, color="black", linewidth=0.8)
        if x_lo <= EQUITY_THRESHOLD_PCT <= x_hi:
            ax.axvline(
                EQUITY_THRESHOLD_PCT,
                color=EQUITY_THRESHOLD_COLOR, linestyle=":", linewidth=1.0,
            )
        ax.set_xlim(x_lo, x_hi)
        ax.set_title(f"{years}Y rolling distribution", fontsize=10)
        ax.set_xlabel("CAGR (%)")
        ax.set_ylabel("# windows")
        ax.grid(True, alpha=0.25)
        # Single legend on the first sub-axis, kept compact.
        if years == ROLLING_WINDOWS_YEARS[0]:
            ax.legend(loc="upper right", fontsize=7, framealpha=0.85)


def _draw_box_plot(
    ax,
    series_per_window: dict[int, tuple[list[float], list[float] | None]],
    *,
    has_bench: bool,
    fund_label: str, bench_label: str | None,
) -> None:
    positions: list[float] = []
    labels: list[str] = []
    fund_groups: list[list[float]] = []
    bench_groups: list[list[float]] = []

    pos = 1
    for years in ROLLING_WINDOWS_YEARS:
        fv, bv = series_per_window.get(years, ([], None))
        if fv:
            fund_groups.append(fv)
            bench_groups.append(bv if bv else [])
            positions.append(pos)
            labels.append(f"{years}Y")
            pos += 1

    if not fund_groups:
        ax.set_axis_off()
        return

    if has_bench:
        # Side-by-side fund + benchmark
        offset = 0.18
        f_pos = [p - offset for p in positions]
        b_pos = [p + offset for p in positions]
        bp_f = ax.boxplot(
            fund_groups, positions=f_pos, widths=0.32,
            patch_artist=True, showfliers=False,
        )
        bp_b = ax.boxplot(
            bench_groups, positions=b_pos, widths=0.32,
            patch_artist=True, showfliers=False,
        )
        for patch in bp_f["boxes"]:
            patch.set_facecolor(FUND_COLOR)
            patch.set_alpha(0.65)
        for patch in bp_b["boxes"]:
            patch.set_facecolor(BENCH_COLOR)
            patch.set_alpha(0.65)
        ax.set_xticks(positions)
        ax.set_xticklabels(labels)
        # Manual legend
        from matplotlib.patches import Patch
        ax.legend(
            handles=[
                Patch(facecolor=FUND_COLOR, alpha=0.65, label=fund_label),
                Patch(facecolor=BENCH_COLOR, alpha=0.65, label=bench_label or "Benchmark"),
            ],
            loc="upper right", fontsize=9,
        )
    else:
        bp = ax.boxplot(
            fund_groups, positions=positions, widths=0.55,
            patch_artist=True, showfliers=False, labels=labels,
        )
        for patch in bp["boxes"]:
            patch.set_facecolor(FUND_COLOR)
            patch.set_alpha(0.65)

    ax.axhline(
        EQUITY_THRESHOLD_PCT,
        color=EQUITY_THRESHOLD_COLOR, linestyle=":", linewidth=1.0,
    )
    ax.axhline(0, color="black", linewidth=0.6)
    ax.set_title("Rolling CAGR distribution by window length", fontsize=11)
    ax.set_ylabel("CAGR (%)")
    ax.grid(True, alpha=0.3)


def _build_figure(
    *,
    fund_name: str, fund_code: str, fund_history: list[NavHistoryPoint],
    bench_name: str | None, bench_history: list[NavHistoryPoint] | None,
    bench_variant: str | None,
    as_of: date,
) -> Figure:
    # Compute per-window rolling series for both.
    series: dict[int, tuple[list[float], list[float] | None]] = {}
    for years in ROLLING_WINDOWS_YEARS:
        _, fund_vals = _rolling_cagr_series(fund_history, years=years, as_of=as_of)
        bench_vals: list[float] | None = None
        if bench_history:
            _, bench_vals = _rolling_cagr_series(
                bench_history, years=years, as_of=as_of,
            )
        series[years] = (fund_vals, bench_vals if bench_history else None)

    # 3Y is the canonical view for the time-series panel (long enough to
    # smooth out volatility, short enough to react to regime changes).
    fund_dates_3y, fund_vals_3y = _rolling_cagr_series(
        fund_history, years=3, as_of=as_of,
    )
    bench_dates_3y: list[date] | None = None
    bench_vals_3y: list[float] | None = None
    if bench_history:
        bench_dates_3y, bench_vals_3y = _rolling_cagr_series(
            bench_history, years=3, as_of=as_of,
        )

    # Layout: 3 stacked panels. We bump the figure height (vs. the natural
    # 13x13 we'd otherwise pick) so the suptitle sits cleanly above the
    # top panel's own title+legend without overlapping. constrained_layout
    # does the inter-axes spacing; the manual top-margin in subplots_adjust
    # below reserves room specifically for the suptitle.
    fig = plt.figure(figsize=(13, 14))
    gs = fig.add_gridspec(
        nrows=3, ncols=4,
        height_ratios=[1.35, 1.0, 1.05],
        hspace=0.42, wspace=0.28,
        top=0.93, bottom=0.05, left=0.06, right=0.97,
    )

    # Panel 1: time series (full width)
    ax_ts = fig.add_subplot(gs[0, :])
    bench_label = (
        f"{bench_name} ({bench_variant})" if bench_name and bench_variant
        else (bench_name if bench_name else None)
    )
    _draw_time_series(
        ax_ts,
        fund_dates_3y, fund_vals_3y,
        bench_dates=bench_dates_3y, bench_values=bench_vals_3y,
        fund_label=fund_name, bench_label=bench_label,
        window_years=3,
    )

    # Panel 2: 4 histograms (one per window)
    axes_hist = [fig.add_subplot(gs[1, c]) for c in range(4)]
    _draw_histograms(
        axes_hist, series,
        fund_label=fund_name, bench_label=bench_label,
    )

    # Panel 3: box plot (full width)
    ax_box = fig.add_subplot(gs[2, :])
    _draw_box_plot(
        ax_box, series,
        has_bench=bench_history is not None,
        fund_label=fund_name, bench_label=bench_label,
    )

    # Two-line suptitle: bold fund name on row 1, dimmer subtitle on row 2.
    # `y` is set just inside the gridspec's top margin (0.93) reserved above.
    bench_blurb = (
        f"  |  benchmark: {bench_label}" if bench_label else "  |  no benchmark configured"
    )
    fig.suptitle(
        f"{fund_name}  ({fund_code})",
        fontsize=14, fontweight="bold", y=0.985,
    )
    fig.text(
        0.5, 0.955,
        f"Rolling-return profile  |  history: "
        f"{fund_history[0].nav_date.isoformat()} → {fund_history[-1].nav_date.isoformat()}"
        f"{bench_blurb}",
        ha="center", va="top", fontsize=10, color="#444444",
    )
    return fig


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate per-fund rolling-return PNGs (3-panel layout, "
                    "with optional benchmark overlay).",
    )
    p.add_argument(
        "--funds", type=Path, default=DEFAULT_FUNDS_PATH,
        help=f"YAML fund list (default: {DEFAULT_FUNDS_PATH.relative_to(PROJECT_ROOT)})",
    )
    p.add_argument(
        "--code", action="append", default=None,
        help="AMFI scheme code(s) to plot. Repeat for multiple. Default: all.",
    )
    p.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
        help=f"Where to write PNGs (default: {DEFAULT_OUTPUT_DIR.relative_to(PROJECT_ROOT)})",
    )
    p.add_argument(
        "--no-benchmark", action="store_true",
        help="Skip benchmark overlay even where mapped.",
    )
    p.add_argument(
        "--refresh-benchmark", action="store_true",
        help="Force-refetch benchmark history.",
    )
    return p.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    log = logging.getLogger("mfhelper.plot_main")

    funds = load_funds(args.funds)
    log.info("Loaded %d fund(s) from %s", len(funds), args.funds)
    if args.code:
        wanted = {c.strip() for c in args.code}
        funds = [f for f in funds if f.code in wanted]
        if not funds:
            log.error("No funds matched --code filter %s", sorted(wanted))
            return 2
        log.info("Filtered to %d fund(s) by --code", len(funds))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    benchmark_map = {} if args.no_benchmark else _load_benchmark_map(BENCHMARKS_PATH)
    bench_cache: dict[str, BenchmarkHistory] = {}

    successes: list[str] = []
    failures: list[str] = []
    for fund in funds:
        log.info("Plotting %s (%s)", fund.code, fund.name or "(no name)")
        result = fetch_history(fund.code)
        if result is None or not result.history:
            log.warning("mfapi.in returned no history for %s; skipping", fund.code)
            failures.append(fund.code)
            continue
        fund_chrono = sorted(result.history, key=lambda p: p.nav_date)
        as_of = fund_chrono[-1].nav_date

        bench_name: str | None = None
        bench_history_navlike: list[NavHistoryPoint] | None = None
        bench_variant: str | None = None
        bench_cfg = benchmark_map.get(fund.code)
        if bench_cfg is not None:
            index_name = bench_cfg["index_name"]
            assert isinstance(index_name, str)
            cached = bench_cache.get(index_name)
            if cached is None:
                cached = fetch_benchmark_history(
                    index_name,
                    variant=str(bench_cfg.get("variant") or "PR"),
                    cache_dir=BENCHMARK_CACHE_DIR,
                    force_refresh=args.refresh_benchmark,
                )
                if cached is not None:
                    bench_cache[index_name] = cached
            if cached is not None:
                bench_name = cached.name
                bench_variant = cached.variant
                bench_history_navlike = _benchmark_to_navlike(cached.history)
            else:
                log.warning(
                    "Benchmark fetch failed for %s; rendering without overlay",
                    fund.code,
                )

        fig = _build_figure(
            fund_name=fund.name or result.scheme_name,
            fund_code=fund.code,
            fund_history=fund_chrono,
            bench_name=bench_name,
            bench_history=bench_history_navlike,
            bench_variant=bench_variant,
            as_of=as_of,
        )
        out_path = args.output_dir / f"{fund.code}.png"
        fig.savefig(out_path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        log.info("  wrote %s (%d bytes)", out_path, out_path.stat().st_size)
        successes.append(fund.code)

    log.info(
        "Done. %d success, %d failure(s).%s%s",
        len(successes), len(failures),
        f" Successes: {', '.join(successes)}" if successes else "",
        f" Failures: {', '.join(failures)}" if failures else "",
    )
    return 0 if not failures else 1


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    log = logging.getLogger("mfhelper.plot_main")
    log.info("=== MFHelper plot run start ===")
    try:
        args = _parse_args(argv)
        return run(args)
    except Exception:
        log.exception("Unhandled error")
        return 3
    finally:
        log.info("=== MFHelper plot run end ===")


if __name__ == "__main__":
    sys.exit(main())
