"""Fund Analytics report generator (one-shot CLI).

Pulls a per-fund analytics row -- 1Y absolute return, 3Y/5Y/7Y/10Y CAGR,
annualized SD, Sharpe, Sortino, and Expense Ratio -- for every entry in
``config/analytics_funds.yaml``, and writes the table to a separate
``Fund Analytics`` worksheet in the same Google Sheet that the daily NAV
job uses.

Run on demand. Independent from the daily 10:30 AM scheduler:

    .venv/bin/python analytics_main.py

Or with a custom fund list / sheet tab:

    .venv/bin/python analytics_main.py --funds config/my_other_list.yaml --tab "My Analytics"

Exit codes:
  0  Success (including soft warnings on individual funds).
  2  Configuration error (no funds, missing sheet ID, etc.).
  3  Unhandled exception.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import logging
import sys

from mfhelper.analytics import compute_analytics
from mfhelper.analytics_sheet import (
    ANALYTICS_TAB_DEFAULT,
    AnalyticsRow,
    AnalyticsSheetWriter,
)
from mfhelper.config import load_analytics_funds, load_settings
from mfhelper.expense_ratio import lookup_expense_ratio
from mfhelper.mfapi import fetch_history

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"

ANALYTICS_FUNDS_PATH = CONFIG_DIR / "analytics_funds.yaml"
SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
CREDENTIALS_PATH = CONFIG_DIR / "credentials.json"
TOKEN_PATH = DATA_DIR / "token.json"


def _configure_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / "mfhelper_analytics.log"
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
        prog="mfhelper-analytics",
        description="Generate the Fund Analytics report into a Google Sheet tab.",
    )
    p.add_argument(
        "--funds",
        type=Path,
        default=ANALYTICS_FUNDS_PATH,
        help="Path to the analytics funds YAML (default: config/analytics_funds.yaml).",
    )
    p.add_argument(
        "--tab",
        type=str,
        default=ANALYTICS_TAB_DEFAULT,
        help=f"Worksheet tab name to write into (default: {ANALYTICS_TAB_DEFAULT!r}).",
    )
    p.add_argument(
        "--no-expense-scrape",
        action="store_true",
        help="Skip the expense-ratio scrape; only use values explicitly set in YAML.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute everything but do not write to Google Sheets (prints to stdout).",
    )
    return p.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    log = logging.getLogger("mfhelper.analytics_main")

    try:
        funds = load_analytics_funds(args.funds)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Configuration error loading {args.funds}: {exc}", file=sys.stderr)
        return 2
    try:
        settings = load_settings(SETTINGS_PATH)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Configuration error loading {SETTINGS_PATH}: {exc}", file=sys.stderr)
        return 2

    tz = ZoneInfo(settings.timezone)
    now_ist = datetime.now(tz)

    log.info(
        "Fund Analytics: %d fund(s) from %s -> %s/%s%s",
        len(funds), args.funds, settings.google_sheet.spreadsheet_id, args.tab,
        " (DRY RUN)" if args.dry_run else "",
    )

    rows: list[AnalyticsRow] = []
    soft_warnings = 0

    for i, fc in enumerate(funds, start=1):
        log.info("[%d/%d] %s (%s)", i, len(funds), fc.name or fc.code, fc.code)

        result = fetch_history(fc.code)
        if result is None:
            log.warning("  No NAV history from mfapi.in for %s -- row will be empty.", fc.code)
            soft_warnings += 1
            display_name = fc.name or fc.code
            rows.append(_empty_row(display_name, fc.code, now_ist))
            continue

        analytics = compute_analytics(result.history)
        log.info(
            "  1Y=%s  3Y=%s  5Y=%s  7Y=%s  10Y=%s  SD=%s  Sharpe=%s  Sortino=%s",
            _fmt_pct(analytics.return_1y_abs_pct),
            _fmt_pct(analytics.cagr_3y_pct),
            _fmt_pct(analytics.cagr_5y_pct),
            _fmt_pct(analytics.cagr_7y_pct),
            _fmt_pct(analytics.cagr_10y_pct),
            _fmt_pct(analytics.sd_pct),
            _fmt(analytics.sharpe),
            _fmt(analytics.sortino),
        )

        # Expense ratio: manual YAML override > auto scrape > blank.
        expense_pct: float | None = fc.expense_ratio_pct
        if expense_pct is not None:
            log.info("  Expense ratio (manual YAML): %.2f%%", expense_pct)
        elif args.no_expense_scrape:
            log.info("  Expense ratio scrape skipped (--no-expense-scrape).")
        else:
            er = lookup_expense_ratio(
                scheme_code=fc.code,
                scheme_name=fc.name or result.scheme_name,
                slug_hint=fc.groww_slug,
            )
            if er is not None:
                expense_pct = er.expense_ratio_pct

        display_name = fc.name or result.scheme_name
        rows.append(AnalyticsRow(
            fund_name=display_name,
            scheme_code=fc.code,
            return_1y_abs_pct=analytics.return_1y_abs_pct,
            cagr_3y_pct=analytics.cagr_3y_pct,
            cagr_5y_pct=analytics.cagr_5y_pct,
            cagr_7y_pct=analytics.cagr_7y_pct,
            cagr_10y_pct=analytics.cagr_10y_pct,
            sd_pct=analytics.sd_pct,
            sharpe=analytics.sharpe,
            sortino=analytics.sortino,
            expense_pct=expense_pct,
            last_updated_ist=now_ist,
        ))

    if args.dry_run:
        log.info("DRY RUN -- not writing to sheet. Computed table:")
        for r in rows:
            print("  ", r.to_cells())
        return 0 if soft_warnings == 0 else 0  # soft warnings don't fail the run

    writer = AnalyticsSheetWriter(
        spreadsheet_id=settings.google_sheet.spreadsheet_id,
        worksheet_name=args.tab,
        credentials_path=CREDENTIALS_PATH,
        token_path=TOKEN_PATH,
    )
    writer.write_table(rows)

    log.info(
        "Done. %d row(s) written; %d fund(s) with no NAV history.",
        len(rows), soft_warnings,
    )
    return 0


def _empty_row(name: str, code: str, now: datetime) -> AnalyticsRow:
    return AnalyticsRow(
        fund_name=name,
        scheme_code=code,
        return_1y_abs_pct=None,
        cagr_3y_pct=None,
        cagr_5y_pct=None,
        cagr_7y_pct=None,
        cagr_10y_pct=None,
        sd_pct=None,
        sharpe=None,
        sortino=None,
        expense_pct=None,
        last_updated_ist=now,
    )


def _fmt_pct(v: float | None) -> str:
    return f"{v:+.2f}%" if v is not None else "-"


def _fmt(v: float | None) -> str:
    return f"{v:.2f}" if v is not None else "-"


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)
    try:
        return run(args)
    except Exception:
        logging.getLogger("mfhelper.analytics_main").exception(
            "Unhandled error during analytics run"
        )
        return 3


if __name__ == "__main__":
    sys.exit(main())
