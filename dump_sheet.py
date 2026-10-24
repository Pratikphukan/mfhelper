"""Dump the Daily NAV Google Sheet to a local CSV file.

Usage:
    .venv/bin/python dump_sheet.py                        # dumps to data/daily_nav_dump.csv
    .venv/bin/python dump_sheet.py --out my_dump.csv      # custom output path
    .venv/bin/python dump_sheet.py --worksheet "Daily NAV (Dev)"  # different tab
    .venv/bin/python dump_sheet.py --print                # print to stdout instead of file

Reuses the existing OAuth credentials in config/credentials.json + data/token.json.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

# Reuse the credential loader already in this project
from mfhelper.sheets import _load_credentials

import gspread

PROJECT_ROOT = Path(__file__).parent
CREDENTIALS_PATH = PROJECT_ROOT / "config" / "credentials.json"
TOKEN_PATH = PROJECT_ROOT / "data" / "token.json"
DEFAULT_OUT = PROJECT_ROOT / "data" / "daily_nav_dump.csv"


def load_settings() -> tuple[str, str]:
    """Return (spreadsheet_id, worksheet_name) from config/settings.yaml."""
    import yaml
    with (PROJECT_ROOT / "config" / "settings.yaml").open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    gs = raw.get("google_sheet", {})
    return gs["spreadsheet_id"], gs.get("worksheet", "Daily NAV")


def dump(worksheet_name: str | None, out_path: Path | None, print_only: bool) -> None:
    spreadsheet_id, default_ws = load_settings()
    ws_name = worksheet_name or default_ws

    print(f"Connecting to spreadsheet {spreadsheet_id!r}, tab {ws_name!r} ...", file=sys.stderr)
    creds = _load_credentials(CREDENTIALS_PATH, TOKEN_PATH)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet = spreadsheet.worksheet(ws_name)

    print("Fetching all values ...", file=sys.stderr)
    rows = worksheet.get_all_values()

    if not rows:
        print("Sheet is empty.", file=sys.stderr)
        return

    print(f"Fetched {len(rows)} rows x {len(rows[0])} columns.", file=sys.stderr)

    if print_only:
        writer = csv.writer(sys.stdout)
        for row in rows:
            writer.writerow(row)
    else:
        dest = out_path or DEFAULT_OUT
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            for row in rows:
                writer.writerow(row)
        print(f"Saved to {dest}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump the Daily NAV sheet to CSV.")
    parser.add_argument("--out", type=Path, default=None, help="Output CSV path (default: data/daily_nav_dump.csv)")
    parser.add_argument("--worksheet", default=None, help="Worksheet tab name (default: from settings.yaml)")
    parser.add_argument("--print", dest="print_only", action="store_true", help="Print CSV to stdout instead of writing a file")
    args = parser.parse_args()

    dump(args.worksheet, args.out, args.print_only)


if __name__ == "__main__":
    main()
