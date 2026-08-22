"""Generate per-fund returns JSON files (one per fund in funds.yaml).

For every fund, fetches the full mfapi.in NAV history once and writes a
structured JSON file at ``data/fund_returns/{code}.json`` containing:

- Trailing returns (1D / 1W / 1M / 3M / 6M / YTD / 1Y absolute / 2Y...10Y CAGR / since-inception)
- Calendar-year returns (one entry per CY since inception, plus current-year YTD)
- Financial-year returns (Apr-Mar boundaries, with current-FY YTD)
- Rolling returns (1Y / 3Y / 5Y / 7Y windows, distribution: count, min/p25/median/p75/max, mean, %negative, %above-12%)
- Risk metrics (annualized SD over 3Y/5Y/since-inception, downside deviation, max-drawdown analysis)
- Risk-adjusted ratios (Sharpe / Sortino over 3Y and 5Y, Calmar 3Y; RFR=7%)
- Extremes (best/worst day + month)
- Hypothetical SIP XIRR (Rs.10,000/month on the 1st, 3Y/5Y/10Y horizons)

Plus an ``unavailable_metrics`` block that names every metric that COULD be
computed given more data (real returns, after-tax, alpha, actual XIRR) and
the data source each one needs.

This is a one-shot CLI -- not part of the daily scheduler. Re-run it
whenever you want a fresh snapshot.

Usage:

    .venv/bin/python returns_main.py                       # all funds in funds.yaml
    .venv/bin/python returns_main.py --code 118551         # one fund
    .venv/bin/python returns_main.py --funds config/analytics_funds.yaml
    .venv/bin/python returns_main.py --dry-run             # compute but don't write
    .venv/bin/python returns_main.py --output-dir /tmp/x   # custom output dir
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from mfhelper.benchmarks import fetch_benchmark_history
from mfhelper.config import load_funds, load_settings
from mfhelper.mfapi import fetch_history
from mfhelper.returns_calc import compute_fund_returns, unavailable_metrics
from mfhelper.returns_writer import FundReturnsWriter
from mfhelper.vs_benchmark import compute_vs_benchmark

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"

DEFAULT_FUNDS_PATH = CONFIG_DIR / "funds.yaml"
DEFAULT_OUTPUT_DIR = DATA_DIR / "fund_returns"
SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
BENCHMARKS_PATH = CONFIG_DIR / "benchmarks.yaml"
BENCHMARK_CACHE_DIR = DATA_DIR / "benchmark_history"


def _load_benchmark_map(path: Path) -> dict[str, dict[str, str]]:
    """Load config/benchmarks.yaml into a {code: {index_name, variant, note}} map.

    Returns an empty dict if the file is missing or empty -- benchmark
    comparison is opt-in and silently skipped for funds without a mapping.
    """
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    entries = raw.get("benchmarks") or []
    out: dict[str, dict[str, str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("code") or "").strip()
        index_name = str(entry.get("index_name") or "").strip()
        if not code or not index_name:
            continue
        out[code] = {
            "index_name": index_name,
            "variant": str(entry.get("variant") or "PR").strip(),
            "note": str(entry.get("note") or "").strip() or None,
        }
    return out


def _configure_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / "mfhelper_returns.log"
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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate per-fund returns JSON files from mfapi.in history.",
    )
    p.add_argument(
        "--funds",
        type=Path,
        default=DEFAULT_FUNDS_PATH,
        help=f"YAML fund list (default: {DEFAULT_FUNDS_PATH.relative_to(PROJECT_ROOT)})",
    )
    p.add_argument(
        "--code",
        action="append",
        default=None,
        help="AMFI scheme code(s) to process. Repeat for multiple. "
             "If omitted, every fund in --funds is processed.",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Where to write JSON files (default: {DEFAULT_OUTPUT_DIR.relative_to(PROJECT_ROOT)})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and print a summary; write no files.",
    )
    p.add_argument(
        "--rfr",
        type=float,
        default=7.0,
        help="Risk-free rate %% for Sharpe/Sortino (default: 7.0).",
    )
    p.add_argument(
        "--no-benchmark",
        action="store_true",
        help="Skip benchmark fetch + vs-benchmark section. Useful when "
             "niftyindices.com is down or you want a faster offline run.",
    )
    p.add_argument(
        "--refresh-benchmark",
        action="store_true",
        help="Force-refetch benchmark history (bypass the local cache).",
    )
    return p.parse_args(argv)


def _summary_line(payload: dict) -> str:
    """One-line digest for the log: fund name, history span, headline return."""
    name = payload.get("scheme_name", "?")
    hist = payload.get("history") or {}
    tr = payload.get("trailing_returns") or {}
    span = (
        f"{hist.get('first_nav_date', '?')} -> {hist.get('latest_nav_date', '?')}"
        if hist else "?"
    )
    cagr_3y = tr.get("3y_cagr_pct")
    si = tr.get("since_inception_cagr_pct")
    cagr_3y_s = f"{cagr_3y:.2f}%" if isinstance(cagr_3y, (int, float)) else "n/a"
    si_s = f"{si:.2f}%" if isinstance(si, (int, float)) else "n/a"
    return f"{name!r}: history {span}; 3Y CAGR {cagr_3y_s}; since-inception CAGR {si_s}"


def _print_returns_summary(payloads: list[dict]) -> None:
    """Print clean, beautiful, aligned summary tables of returns and risk metrics directly to the terminal."""
    if not payloads:
        return
        
    print("\n" + "=" * 110)
    print("📈 PORTFOLIO TRAILING PERFORMANCE SUMMARY")
    print("=" * 110)
    print(f"{'Fund Name':<45} | {'1Y (Abs)':<10} | {'3Y (CAGR)':<12} | {'5Y (CAGR)':<12} | {'10Y (CAGR)':<12} | {'Inception':<12}")
    print("-" * 110)
    for p in payloads:
        tr = p.get("trailing_returns") or {}
        name = p.get("scheme_name", "?")[:43]
        
        def f_val(val):
            return f"{val:.2f}%" if isinstance(val, (int, float)) else "n/a"
            
        y1 = f_val(tr.get("1y_abs_pct"))
        y3 = f_val(tr.get("3y_cagr_pct"))
        y5 = f_val(tr.get("5y_cagr_pct"))
        y10 = f_val(tr.get("10y_cagr_pct"))
        si = f_val(tr.get("since_inception_cagr_pct"))
        print(f"{name:<45} | {y1:<10} | {y3:<12} | {y5:<12} | {y10:<12} | {si:<12}")
    print("=" * 110)

    print("\n" + "=" * 110)
    print("🛒 HYPOTHETICAL MONTHLY SIP XIRR SUMMARY (Rs. 10,000/month)")
    print("=" * 110)
    print(f"{'Fund Name':<45} | {'3Y SIP XIRR':<15} | {'5Y SIP XIRR':<15} | {'10Y SIP XIRR':<15}")
    print("-" * 110)
    for p in payloads:
        sip = p.get("hypothetical_sip_xirr") or {}
        name = p.get("scheme_name", "?")[:43]
        
        def f_val(val):
            return f"{val:.2f}%" if isinstance(val, (int, float)) else "n/a"
            
        s3 = f_val(sip.get("3y_xirr_pct"))
        s5 = f_val(sip.get("5y_xirr_pct"))
        s10 = f_val(sip.get("10y_xirr_pct"))
        print(f"{name:<45} | {s3:<15} | {s5:<15} | {s10:<15}")
    print("=" * 110)

    print("\n" + "=" * 110)
    print("🛡️ RISK METRICS & PERFORMANCE RATIOS (3Y Window)")
    print("=" * 110)
    print(f"{'Fund Name':<45} | {'Ann. SD %':<12} | {'Sharpe':<12} | {'Sortino':<12} | {'Calmar':<12}")
    print("-" * 110)
    for p in payloads:
        risk = p.get("risk") or {}
        ra = p.get("risk_adjusted") or {}
        name = p.get("scheme_name", "?")[:43]
        
        def f_val(val):
            return f"{val:.2f}%" if isinstance(val, (int, float)) else "n/a"
            
        def f_rat(val):
            return f"{val:.2f}" if isinstance(val, (int, float)) else "n/a"
            
        sd = f_val(risk.get("sd_3y_pct"))
        sharpe = f_rat(ra.get("sharpe_3y"))
        sortino = f_rat(ra.get("sortino_3y"))
        calmar = f_rat(ra.get("calmar_3y"))
        print(f"{name:<45} | {sd:<12} | {sharpe:<12} | {sortino:<12} | {calmar:<12}")
    print("=" * 110)


def run(args: argparse.Namespace) -> int:
    log = logging.getLogger("mfhelper.returns_main")

    settings = load_settings(SETTINGS_PATH)
    tz = ZoneInfo(settings.timezone)
    computed_at = datetime.now(tz).isoformat(timespec="seconds")

    funds = load_funds(args.funds)
    log.info("Loaded %d fund(s) from %s", len(funds), args.funds)
    if args.code:
        wanted = {c.strip() for c in args.code}
        filtered_funds = [f for f in funds if f.code in wanted]
        
        # If some codes are missing from the YAML, dynamically generate placeholder FundConfig objects!
        found_codes = {f.code for f in filtered_funds}
        missing_codes = [c for c in wanted if c not in found_codes]
        if missing_codes:
            from mfhelper.config import FundConfig
            for mc in missing_codes:
                filtered_funds.append(FundConfig(code=mc, name=None))
                
        funds = filtered_funds
        log.info("Resolved %d fund(s) for --code query (%d from config list, %d dynamic placeholders)", len(funds), len(found_codes), len(missing_codes))

    writer = FundReturnsWriter(args.output_dir)
    benchmark_map = {} if args.no_benchmark else _load_benchmark_map(BENCHMARKS_PATH)
    if benchmark_map:
        log.info(
            "Loaded %d benchmark mapping(s) from %s",
            len(benchmark_map), BENCHMARKS_PATH,
        )

    successes: list[str] = []
    failures: list[str] = []
    successful_payloads: list[dict] = []
    benchmark_cache: dict[str, object] = {}  # name -> BenchmarkHistory
    for fund in funds:
        log.info(
            "Processing %s (%s)", fund.code, fund.name or "(no display name)"
        )
        result = fetch_history(fund.code)
        if result is None or not result.history:
            log.warning(
                "mfapi.in returned no history for %s; skipping", fund.code
            )
            failures.append(fund.code)
            continue

        sections = compute_fund_returns(
            result.history, risk_free_rate_pct=args.rfr,
        )

        # Optional vs-benchmark section. Only attached when (a) the fund
        # has a benchmark mapping, (b) the benchmark fetch succeeded.
        vs_bench_section: dict[str, object] | None = None
        bench_cfg = benchmark_map.get(fund.code)
        if bench_cfg is not None:
            index_name = bench_cfg["index_name"]
            cached_bench = benchmark_cache.get(index_name)
            if cached_bench is None:
                cached_bench = fetch_benchmark_history(
                    index_name,
                    variant=bench_cfg.get("variant", "PR"),
                    cache_dir=BENCHMARK_CACHE_DIR,
                    force_refresh=args.refresh_benchmark,
                )
                if cached_bench is not None:
                    benchmark_cache[index_name] = cached_bench
            if cached_bench is None:
                log.warning(
                    "Benchmark fetch failed for %s (index %r); "
                    "skipping vs_benchmark section",
                    fund.code, index_name,
                )
            else:
                # cached_bench is a BenchmarkHistory; pull .history etc.
                from mfhelper.benchmarks import BenchmarkHistory
                assert isinstance(cached_bench, BenchmarkHistory)
                vs_bench_section = compute_vs_benchmark(
                    result.history,
                    cached_bench.history,
                    benchmark_name=cached_bench.name,
                    variant=cached_bench.variant,
                    benchmark_note=bench_cfg.get("note"),
                )

        payload: dict = {
            "schema_version": 1,
            "scheme_code": fund.code,
            "scheme_name": fund.name or result.scheme_name,
            "computed_at": computed_at,
            "data_source": "api.mfapi.in",
            **sections,
        }
        if vs_bench_section is not None:
            payload["vs_benchmark"] = vs_bench_section
        payload["unavailable_metrics"] = unavailable_metrics()
        payload["notes"] = [
            "All NAVs are Direct-plan, Growth-option (already total-return).",
            "Pre-tax. Nominal (not inflation-adjusted).",
            "Trailing-window returns: <1Y are absolute, multi-year are CAGR.",
            "Rolling-window CAGRs use a daily stride; windows overlap by design.",
            "Risk metrics annualized via sqrt(252).",
            f"Risk-free rate for Sharpe/Sortino: {args.rfr:.2f}% (set via --rfr).",
            "Hypothetical SIP: Rs.10,000 buy on the 1st of each month "
            "(or the next available NAV publish day); horizons skipped if "
            "longer than the fund's available history.",
        ]

        log.info("  %s", _summary_line(payload))

        if args.dry_run:
            preview = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
            head = preview[:1500]
            log.info(
                "DRY RUN: would write %s (%d JSON chars). First 1500 chars:\n%s%s",
                args.output_dir / f"{fund.code}.json",
                len(preview),
                head,
                "\n  ... (truncated) ..." if len(preview) > 1500 else "",
            )
        else:
            path = writer.write(fund.code, payload)
            log.info("  wrote %s (%d bytes)", path, path.stat().st_size)
        successes.append(fund.code)
        successful_payloads.append(payload)

    _print_returns_summary(successful_payloads)

    log.info(
        "Done. %d success, %d failure(s).%s%s",
        len(successes),
        len(failures),
        f" Successes: {', '.join(successes)}" if successes else "",
        f" Failures: {', '.join(failures)}" if failures else "",
    )
    return 0 if not failures else 1


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    log = logging.getLogger("mfhelper.returns_main")
    log.info("=== MFHelper returns run start ===")
    try:
        args = _parse_args(argv)
        return run(args)
    except Exception:
        log.exception("Unhandled error")
        return 3
    finally:
        log.info("=== MFHelper returns run end ===")


if __name__ == "__main__":
    sys.exit(main())
