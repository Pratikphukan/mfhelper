"""One-shot cleanup: remove duplicate same-day rows from the Daily NAV sheet.

For each date that has more than one row, keeps the LAST row (most recent
timestamp) and deletes all earlier ones.

Usage:
    .venv/bin/python cleanup_duplicates.py                        # dry-run by default
    .venv/bin/python cleanup_duplicates.py --write                # actually delete rows
    .venv/bin/python cleanup_duplicates.py --worksheet "Daily NAV (Dev)"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mfhelper.sheets import _load_credentials, HEADER_ROWS

import gspread

PROJECT_ROOT = Path(__file__).parent
CREDENTIALS_PATH = PROJECT_ROOT / "config" / "credentials.json"
TOKEN_PATH = PROJECT_ROOT / "data" / "token.json"


def load_settings() -> tuple[str, str]:
    import yaml
    with (PROJECT_ROOT / "config" / "settings.yaml").open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    gs = raw.get("google_sheet", {})
    return gs["spreadsheet_id"], gs.get("worksheet", "Daily NAV")


def cleanup(worksheet_name: str | None, dry_run: bool) -> None:
    spreadsheet_id, default_ws = load_settings()
    ws_name = worksheet_name or default_ws

    print(f"Connecting to spreadsheet {spreadsheet_id!r}, tab {ws_name!r} ...")
    creds = _load_credentials(CREDENTIALS_PATH, TOKEN_PATH)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet = spreadsheet.worksheet(ws_name)

    print("Fetching timestamps ...")
    timestamps = worksheet.col_values(1)
    data_timestamps = timestamps[HEADER_ROWS:] if len(timestamps) > HEADER_ROWS else []

    # Group sheet row numbers (1-based) by date.
    from collections import defaultdict
    date_to_rows: dict[str, list[int]] = defaultdict(list)
    for i, ts in enumerate(data_timestamps):
        date = ts.split(" ", 1)[0] if ts else ""
        if date:
            sheet_row = HEADER_ROWS + 1 + i
            date_to_rows[date].append(sheet_row)

    # Find dates with duplicates.
    duplicates = {d: rows for d, rows in date_to_rows.items() if len(rows) > 1}

    if not duplicates:
        print("No duplicate rows found. Sheet is clean.")
        return

    total_to_delete = sum(len(rows) - 1 for rows in duplicates.values())
    print(f"\nFound {len(duplicates)} date(s) with duplicates ({total_to_delete} rows to delete):\n")
    for date in sorted(duplicates):
        rows = duplicates[date]
        print(f"  {date}: {len(rows)} rows (sheet rows {rows}) -> keeping row {rows[-1]}, deleting {rows[:-1]}")

    if dry_run:
        print(f"\n[DRY RUN] No changes made. Re-run with --write to apply.")
        return

    print(f"\nDeleting {total_to_delete} duplicate row(s) ...")

    # Delete from bottom to top so row indices don't shift mid-loop.
    rows_to_delete: list[int] = []
    for rows in duplicates.values():
        rows_to_delete.extend(rows[:-1])  # all except the last (most recent)
    rows_to_delete.sort(reverse=True)

    deleted = 0
    for sheet_row in rows_to_delete:
        worksheet.delete_rows(sheet_row)
        deleted += 1
        print(f"  Deleted sheet row {sheet_row} ({deleted}/{total_to_delete})")

    print(f"\nDone. Deleted {deleted} duplicate row(s).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean up duplicate same-day rows in the Daily NAV sheet.")
    parser.add_argument("--write", action="store_true", help="Actually delete rows (default is dry-run)")
    parser.add_argument("--worksheet", default=None, help="Worksheet tab name (default: from settings.yaml)")
    args = parser.parse_args()

    cleanup(args.worksheet, dry_run=not args.write)


if __name__ == "__main__":
    main()
