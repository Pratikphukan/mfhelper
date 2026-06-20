"""One-shot CLI: backfill historical Daily NAV rows for a single fund.

When a fund is added to ``config/funds.yaml`` mid-stream, the Daily NAV
worksheet ends up with that fund's column populated only for runs from
the addition date onward -- earlier rows in the rolling 30-day window
are blank for that fund. This CLI fills those gaps in place.

Mechanics:

1. Reads each historical run-timestamp from column A.
2. Resolves each run-date to the fund's NAV by looking up the most
   recent ``mfapi.in`` NAV-publish on or before that date. This matches
   the live scheduler's weekend/holiday behaviour: on a weekend run-date,
   you get Friday's NAV (so Day Change %% lands at 0%% on Sat/Sun, exactly
   as if the scheduler had been running daily).
3. Recomputes Day Change %, Dist 52W H%, Dist 200D SMA %, and RSI(14)
   for each row using the same metric helpers as the daily scheduler --
   values are bit-exact equivalents of what the scheduler would have
   written on those days.
4. Writes ONLY into cells that are currently blank by default. Pass
   ``--overwrite`` to refill non-blank cells too (use with care: it
   overwrites, not appends).

Refuses to run if the worksheet's physical fund-group count doesn't
match ``data/sheet_columns.json``. That mismatch usually means an
orphan column block (a fund removed from ``funds.yaml`` but still
physically present in the sheet) needs to be deleted in Google Sheets
first.

Usage:

    .venv/bin/python backfill_main.py --code 118551 --dry-run
    .venv/bin/python backfill_main.py --code 118551
    .venv/bin/python backfill_main.py --code 118551 --overwrite
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import gspread
from gspread.utils import rowcol_to_a1

from mfhelper.columns import SheetColumnStore
from mfhelper.config import load_settings
from mfhelper.metrics import (
    distance_from_200d_sma,
    distance_from_52w_high,
    rsi as compute_rsi,
)
from mfhelper.mfapi import NavHistoryPoint, fetch_history
from mfhelper.sheets import (
    DATA_START_ROW,
    HEADER_ROWS,
    NAV_LABEL,
    SUB_COLS_PER_FUND,
    _load_credentials,
)

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"

SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
CREDENTIALS_PATH = CONFIG_DIR / "credentials.json"
TOKEN_PATH = DATA_DIR / "token.json"
COLUMNS_PATH = DATA_DIR / "sheet_columns.json"

# Sheets serial-date origin (the so-called "Lotus 1-2-3 epoch").
_SHEETS_EPOCH = datetime(1899, 12, 30)


def _configure_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / "mfhelper_backfill.log"
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
        description="Backfill historical Daily NAV rows for a single fund.",
    )
    p.add_argument(
        "--code",
        required=True,
        help="AMFI scheme code (e.g. 118551 for Franklin US Opportunities). "
        "Must already be present in data/sheet_columns.json.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and print updates without writing to the sheet.",
    )
    p.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite cells that already contain values. Default: skip them.",
    )
    return p.parse_args(argv)


def _parse_run_date(raw: object) -> date | None:
    """Tolerantly parse a column-A timestamp into a date.

    Handles three encodings the cell may surface in:
      * Plain string ``"2026-05-23 15:00:51"`` (raw string written by the
        scheduler, when the cell hasn't been auto-coerced to a date).
      * Localized display strings such as ``"5/23/2026 15:00:51"`` or
        ``"23/5/2026 ..."`` (when Sheets did auto-coerce to a date type
        and gspread is returning the FORMATTED_VALUE).
      * Sheets serial number (``45810.62559...``) when reading with
        UNFORMATTED_VALUE.
    """
    if isinstance(raw, (int, float)):
        return (_SHEETS_EPOCH + timedelta(days=float(raw))).date()
    s = str(raw).strip()
    if not s:
        return None
    if " " in s:
        s = s.split(" ", 1)[0]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _nav_at_or_before(
    history: list[NavHistoryPoint], target: date
) -> NavHistoryPoint | None:
    """Most recent NAV publish on or before ``target`` (None if none exists)."""
    best: NavHistoryPoint | None = None
    for point in history:
        if point.nav_date <= target and (best is None or point.nav_date > best.nav_date):
            best = point
    return best


def _verify_layout(
    worksheet: gspread.Worksheet, expected_groups: int
) -> int:
    """Confirm the sheet's physical fund-group count matches state.

    Returns the count on success. Raises RuntimeError with actionable
    instructions on mismatch.
    """
    row2 = worksheet.row_values(2)
    label_count = max(len(row2) - 1, 0)  # exclude A2 (run-timestamp header)
    if label_count == 0:
        raise RuntimeError(
            "Worksheet header row 2 is empty. Run main.py at least once first "
            "so the wide-format header is initialised."
        )
    if label_count % SUB_COLS_PER_FUND != 0:
        raise RuntimeError(
            f"Worksheet row 2 has {label_count} sub-label cell(s), not a "
            f"multiple of {SUB_COLS_PER_FUND}. Header is corrupted; aborting."
        )
    physical_groups = label_count // SUB_COLS_PER_FUND
    if physical_groups != expected_groups:
        raise RuntimeError(
            f"Layout mismatch: worksheet has {physical_groups} physical fund "
            f"group(s) but data/sheet_columns.json lists {expected_groups}. "
            "This usually means an orphan column block needs to be removed "
            "from the sheet (or sheet_columns.json needs another code added).\n\n"
            "Most likely fix: delete the obsolete 5-column block in Google "
            "Sheets, then re-run this script. Backfill is intentionally "
            "refusing to write into a misaligned sheet to avoid scrambling "
            "fund columns."
        )
    # Sanity-check the first sub-label as a tripwire for the wrong layout.
    if row2[1].strip() != NAV_LABEL:
        raise RuntimeError(
            f"Row 2 column B reads {row2[1]!r}, expected {NAV_LABEL!r}. "
            "Worksheet does not match the expected wide-format layout."
        )
    return physical_groups


def _col_letters(col_index: int) -> str:
    return "".join(ch for ch in rowcol_to_a1(1, col_index) if ch.isalpha())


def run(args: argparse.Namespace) -> int:
    log = logging.getLogger("mfhelper.backfill_main")
    settings = load_settings(SETTINGS_PATH)
    code = str(args.code).strip()

    # 1. Find target fund's logical column position.
    col_store = SheetColumnStore(COLUMNS_PATH)
    columns = col_store.load()
    if code not in columns:
        log.error(
            "Code %s is not in data/sheet_columns.json. Add the fund to "
            "config/funds.yaml and run main.py once so its column gets "
            "appended to the sheet, then re-run this script.",
            code,
        )
        return 2
    fund_position = columns.index(code)  # 0-based

    nav_col = 2 + SUB_COLS_PER_FUND * fund_position
    rsi_col = nav_col + SUB_COLS_PER_FUND - 1
    nav_letter = _col_letters(nav_col)
    rsi_letter = _col_letters(rsi_col)
    log.info(
        "Code %s -> position %d (logical columns %s..%s, NAV..RSI)",
        code,
        fund_position,
        nav_letter,
        rsi_letter,
    )

    # 2. Connect to the sheet and verify alignment.
    creds = _load_credentials(CREDENTIALS_PATH, TOKEN_PATH)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(settings.google_sheet.spreadsheet_id)
    worksheet = spreadsheet.worksheet(settings.google_sheet.worksheet)
    _verify_layout(worksheet, expected_groups=len(columns))
    log.info(
        "Layout verified: %d fund group(s), aligned with state.", len(columns)
    )

    # 3. Read run-timestamps from column A (rows 3..N).
    col_a = worksheet.col_values(1)
    timestamps_raw = col_a[HEADER_ROWS:]
    if not timestamps_raw:
        log.info("No data rows in the sheet -- nothing to backfill.")
        return 0
    log.info("Sheet has %d data row(s).", len(timestamps_raw))

    # 4. Read the existing values in the fund's 5-column block.
    block_range = (
        f"{nav_letter}{DATA_START_ROW}:"
        f"{rsi_letter}{HEADER_ROWS + len(timestamps_raw)}"
    )
    block = worksheet.get(block_range)
    while len(block) < len(timestamps_raw):
        block.append([])
    block = [(row + [""] * SUB_COLS_PER_FUND)[:SUB_COLS_PER_FUND] for row in block]

    # 5. Fetch the fund's full NAV history once.
    log.info("Fetching mfapi.in history for %s ...", code)
    result = fetch_history(code)
    if result is None or not result.history:
        log.error(
            "mfapi.in returned no NAV history for %s. Cannot backfill.", code
        )
        return 2
    log.info(
        "Loaded %d NAV publish day(s) (%s..%s) for %r",
        len(result.history),
        result.history[-1].nav_date,
        result.history[0].nav_date,
        result.scheme_name,
    )

    # 6. Walk rows in chronological order, computing each row's metrics
    #    and chaining DC%% off whichever NAV anchored the previous row
    #    (existing if non-blank, else freshly computed).
    updates: list[tuple[int, list[object]]] = []  # (sheet_row, [5 values])
    skipped_already_filled = 0
    skipped_no_nav = 0
    skipped_unparseable_ts = 0
    prev_nav: float | None = None

    for i, ts_raw in enumerate(timestamps_raw):
        sheet_row = HEADER_ROWS + 1 + i  # 1-based row number in the sheet
        existing = block[i]
        existing_nav_str = str(existing[0]).strip()
        nav_already_present = existing_nav_str != ""

        run_date = _parse_run_date(ts_raw)
        if run_date is None:
            skipped_unparseable_ts += 1
            log.warning(
                "Row %d: could not parse timestamp %r; skipping",
                sheet_row,
                ts_raw,
            )
            # Still update prev_nav using the existing NAV (best effort)
            # so we don't break the chain for later rows.
            try:
                prev_nav = (
                    float(existing_nav_str.replace(",", ""))
                    if existing_nav_str
                    else prev_nav
                )
            except ValueError:
                pass
            continue

        nav_point = _nav_at_or_before(result.history, run_date)
        if nav_point is None:
            skipped_no_nav += 1
            log.info(
                "Row %d (%s): no NAV publish at or before this date; cell stays blank",
                sheet_row,
                run_date.isoformat(),
            )
            continue

        new_nav = nav_point.nav

        if nav_already_present and not args.overwrite:
            # Honour the existing NAV value as the chain anchor for the
            # next row. Live scheduler may have published a slightly
            # different rounding; we prefer the on-sheet value to avoid
            # drift in the DC%% column.
            try:
                prev_nav = float(existing_nav_str.replace(",", ""))
            except ValueError:
                prev_nav = new_nav
            skipped_already_filled += 1
            continue

        if prev_nav is not None and prev_nav > 0:
            day_change_pct: float | None = round(
                (new_nav - prev_nav) / prev_nav * 100, 4
            )
        else:
            day_change_pct = None

        dist_52w = distance_from_52w_high(
            result.history, new_nav, nav_point.nav_date
        )
        dist_200d = distance_from_200d_sma(
            result.history, new_nav, nav_point.nav_date
        )
        rsi_value = compute_rsi(result.history, new_nav, nav_point.nav_date)

        cells: list[object] = [
            new_nav,
            "" if day_change_pct is None else day_change_pct,
            "" if dist_52w is None else dist_52w,
            "" if dist_200d is None else dist_200d,
            "" if rsi_value is None else rsi_value,
        ]
        updates.append((sheet_row, cells))
        prev_nav = new_nav

    log.info(
        "Plan: %d update(s); skipped %d already-filled, %d unparseable timestamps, "
        "%d with no NAV history.",
        len(updates),
        skipped_already_filled,
        skipped_unparseable_ts,
        skipped_no_nav,
    )

    if updates:
        preview_n = min(5, len(updates))
        log.info("First %d planned update(s):", preview_n)
        for sheet_row, cells in updates[:preview_n]:
            log.info(
                "  row %d  NAV=%s  DC%%=%s  52W%%=%s  200D%%=%s  RSI=%s",
                sheet_row,
                cells[0],
                cells[1],
                cells[2],
                cells[3],
                cells[4],
            )

    if args.dry_run:
        log.info("--dry-run: not writing to the sheet.")
        return 0
    if not updates:
        log.info("Nothing to write.")
        return 0

    # 7. Single batch_update -- one range per row, USER_ENTERED so the
    #    existing per-column number formats render the values correctly.
    batch_data = [
        {
            "range": f"{nav_letter}{sheet_row}:{rsi_letter}{sheet_row}",
            "values": [cells],
        }
        for sheet_row, cells in updates
    ]
    worksheet.batch_update(batch_data, value_input_option="USER_ENTERED")
    log.info(
        "Wrote %d backfill row(s) into %r (column block %s..%s).",
        len(updates),
        settings.google_sheet.worksheet,
        nav_letter,
        rsi_letter,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    log = logging.getLogger("mfhelper.backfill_main")
    log.info("=== MFHelper backfill run start ===")
    try:
        args = _parse_args(argv)
        return run(args)
    except Exception:
        log.exception("Unhandled error during backfill")
        return 3
    finally:
        log.info("=== MFHelper backfill run end ===")


if __name__ == "__main__":
    sys.exit(main())
