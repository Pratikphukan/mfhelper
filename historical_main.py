"""Per-fund historical drilldown report (one-shot CLI).

For a single AMFI scheme code, fetches the NAV history from mfapi.in,
recomputes NAV / Day Change % / Dist 52W H% / Dist 200D SMA % / RSI(14)
for every NAV-publish date in the trailing window, and writes the result
to its own worksheet tab in the same Google Sheet.

Examples:

    # 30 days, default tab name derived from the fund name
    .venv/bin/python historical_main.py --code 118551

    # 60 days, custom tab name
    .venv/bin/python historical_main.py --code 118551 --days 60 --tab "Franklin US Opp 60D"

    # Print only, don't touch the sheet
    .venv/bin/python historical_main.py --code 118551 --dry-run

Exit codes:
  0  success (including soft warnings).
  2  configuration error.
  3  unhandled exception.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import logging
import re
import sys

from mfhelper.config import load_settings
from mfhelper.historical import compute_historical_rows
from mfhelper.historical_sheet import (
    HistoricalSheetMeta,
    HistoricalSheetWriter,
)
from mfhelper.mfapi import fetch_history

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"

SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
CREDENTIALS_PATH = CONFIG_DIR / "credentials.json"
TOKEN_PATH = DATA_DIR / "token.json"

DEFAULT_DAYS = 30
TAB_NAME_MAX_LEN = 80  # Google Sheets tab-name limit is 100 chars; leave headroom.


def _configure_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / "mfhelper_historical.log"
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
        prog="mfhelper-historical",
        description="Per-fund N-day historical drilldown -> Google Sheet tab.",
    )
    p.add_argument(
        "--code",
        type=str,
        required=True,
        help="AMFI scheme code (e.g. 118551 for Franklin U.S. Opportunities).",
    )
    p.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"Number of trailing NAV-publish days to include (default: {DEFAULT_DAYS}).",
    )
    p.add_argument(
        "--tab",
        type=str,
        default=None,
        help="Worksheet tab name. Default: derived from fund name + '<days>D'.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute & print only; do not write to Google Sheets.",
    )
    return p.parse_args(argv)


def _derive_tab_name(fund_name: str, days: int) -> str:
    """Slim down a long AMFI scheme name into a clean tab title.

    AMFI names are verbose (``Franklin U.S. Opportunities Equity Active
    Fund of Funds - Direct - Growth``). We strip plan/option boilerplate
    and trailing direct/growth markers, then suffix the window length.
    """
    s = fund_name
    # Strip noise suffixes typical in AMFI names.
    for noise in (
        " - Direct - Growth",
        " - Direct Plan - Growth",
        " - Direct Plan-Growth",
        "-Direct Plan-Growth",
        " - Growth",
        " - IDCW",
    ):
        s = s.replace(noise, "")
    s = re.sub(r"\s+", " ", s).strip(" -")
    suffix = f" {days}D"
    if len(s) + len(suffix) > TAB_NAME_MAX_LEN:
        s = s[: TAB_NAME_MAX_LEN - len(suffix)].rstrip(" -")
    return s + suffix


def run(args: argparse.Namespace) -> int:
    log = logging.getLogger("mfhelper.historical_main")

    if args.days < 1:
        print("--days must be >= 1", file=sys.stderr)
        return 2

    try:
        settings = load_settings(SETTINGS_PATH)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Configuration error loading {SETTINGS_PATH}: {exc}", file=sys.stderr)
        return 2

    code = str(args.code).strip()
    log.info("Fetching NAV history for AMFI scheme %s ...", code)
    result = fetch_history(code)
    if result is None or not result.history:
        log.error(
            "mfapi.in returned no NAV history for %s. Check the code at "
            "https://www.amfiindia.com/spages/NAVAll.txt", code,
        )
        return 2

    log.info(
        "Loaded %d NAV publish day(s) for %s (oldest=%s, newest=%s)",
        len(result.history), result.scheme_name,
        result.history[-1].nav_date, result.history[0].nav_date,
    )

    rows = compute_historical_rows(result.history, days=args.days)
    if not rows:
        log.error("No rows produced. History was empty after sorting.")
        return 2

    log.info(
        "Computed %d row(s); newest=%s NAV=%.4f, oldest=%s NAV=%.4f",
        len(rows),
        rows[0].nav_date, rows[0].nav,
        rows[-1].nav_date, rows[-1].nav,
    )

    tab = args.tab or _derive_tab_name(result.scheme_name, args.days)
    log.info("Target tab: %r", tab)

    if args.dry_run:
        log.info("DRY RUN -- not writing to sheet. First 5 / last 2 rows:")
        for r in rows[:5]:
            print(_format_dryrun_row(r))
        if len(rows) > 7:
            print("  ...")
        for r in rows[-2:]:
            print(_format_dryrun_row(r))
        return 0

    tz = ZoneInfo(settings.timezone)
    meta = HistoricalSheetMeta(
        fund_name=result.scheme_name,
        scheme_code=code,
        days_requested=args.days,
        last_updated_ist=datetime.now(tz),
    )
    writer = HistoricalSheetWriter(
        spreadsheet_id=settings.google_sheet.spreadsheet_id,
        worksheet_name=tab,
        credentials_path=CREDENTIALS_PATH,
        token_path=TOKEN_PATH,
    )
    writer.write_table(rows, meta)
    log.info("Done. %d row(s) written to %r.", len(rows), tab)
    return 0


def _format_dryrun_row(r) -> str:
    def _pct(v):
        return f"{v:+.2f}%" if v is not None else "      -"

    def _rsi(v):
        return f"{v:6.2f}" if v is not None else "     -"

    return (
        f"  {r.nav_date}  NAV={r.nav:>10.4f}  "
        f"DC={_pct(r.day_change_pct)}  "
        f"52W={_pct(r.dist_52w_high_pct)}  "
        f"200D={_pct(r.dist_200d_sma_pct)}  "
        f"RSI={_rsi(r.rsi_14)}"
    )


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)
    try:
        return run(args)
    except Exception:
        logging.getLogger("mfhelper.historical_main").exception(
            "Unhandled error during historical run"
        )
        return 3


if __name__ == "__main__":
    sys.exit(main())
