"""Sheet writer for the per-fund historical drilldown tab.

Single-table layout (one row per NAV-publish date, newest first):

    | Date | NAV | Day Change % | Dist from 52W High % | Dist from 200D SMA % | RSI (14) |
    | 2026-05-16 | 60.1234 |   0.34% |  -1.23% |   3.45% | 58.42 |
    | 2026-05-15 | ...

The first row above the table is a 1-row "info banner" showing the fund
name and AMFI scheme code so the tab is self-describing. Frozen header
row, per-column number formats, tab overwritten on every run.

OAuth & retry plumbing is shared with :mod:`mfhelper.sheets` /
:mod:`mfhelper.analytics_sheet`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import logging
import time

import gspread
from gspread.utils import rowcol_to_a1

from mfhelper.historical import HistoricalRow
from mfhelper.sheets import _load_credentials

log = logging.getLogger(__name__)

HEADERS = (
    "Date",
    "NAV",
    "Day Change %",
    "Dist from 52W High %",
    "Dist from 200D SMA %",
    "RSI (14)",
)

_NAV_FMT = {"type": "NUMBER", "pattern": "0.0000"}
_PCT_FMT = {"type": "NUMBER", "pattern": '0.00"%"'}
_RSI_FMT = {"type": "NUMBER", "pattern": "0.00"}

# Per-column number formats for data rows, aligned with HEADERS.
_COLUMN_FORMATS = (
    None,           # Date (text yyyy-mm-dd)
    _NAV_FMT,       # NAV
    _PCT_FMT,       # Day Change %
    _PCT_FMT,       # Dist 52W
    _PCT_FMT,       # Dist 200D SMA
    _RSI_FMT,       # RSI
)

RETRY_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = 2.0


@dataclass(frozen=True)
class HistoricalSheetMeta:
    """Tab-level metadata rendered as the info banner row."""
    fund_name: str
    scheme_code: str
    days_requested: int
    last_updated_ist: datetime


class HistoricalSheetWriter:
    def __init__(
        self,
        spreadsheet_id: str,
        worksheet_name: str,
        credentials_path: Path,
        token_path: Path,
    ) -> None:
        self._spreadsheet_id = spreadsheet_id
        self._worksheet_name = worksheet_name
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._client: gspread.Client | None = None
        self._worksheet: gspread.Worksheet | None = None

    def _connect(self) -> gspread.Worksheet:
        if self._worksheet is not None:
            return self._worksheet
        creds = _load_credentials(self._credentials_path, self._token_path)
        self._client = gspread.authorize(creds)
        spreadsheet = self._client.open_by_key(self._spreadsheet_id)
        try:
            ws = spreadsheet.worksheet(self._worksheet_name)
        except gspread.WorksheetNotFound:
            log.info("Worksheet %r not found; creating", self._worksheet_name)
            ws = spreadsheet.add_worksheet(
                title=self._worksheet_name,
                rows=80,
                cols=len(HEADERS) + 2,
            )
        self._worksheet = ws
        return ws

    @staticmethod
    def _run_with_retry(call):
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                return call()
            except gspread.exceptions.APIError as exc:
                status = (
                    getattr(exc.response, "status_code", None)
                    if hasattr(exc, "response")
                    else None
                )
                if attempt < RETRY_ATTEMPTS and (
                    status is None or status in (429, 500, 502, 503, 504)
                ):
                    sleep_s = RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
                    log.info(
                        "Sheets API attempt %d/%d failed (HTTP %s); retry in %.1fs",
                        attempt, RETRY_ATTEMPTS, status, sleep_s,
                    )
                    time.sleep(sleep_s)
                    continue
                raise

    def write_table(
        self,
        rows: list[HistoricalRow],
        meta: HistoricalSheetMeta,
    ) -> None:
        ws = self._connect()
        self._run_with_retry(ws.clear)

        info_banner = (
            f"{meta.fund_name}  |  AMFI {meta.scheme_code}  |  "
            f"last {meta.days_requested} NAV-publish days  |  "
            f"updated {meta.last_updated_ist.strftime('%Y-%m-%d %H:%M:%S IST')}"
        )

        table: list[list] = []
        table.append([info_banner])
        table.append(list(HEADERS))
        for r in rows:
            table.append([
                r.nav_date.strftime("%Y-%m-%d"),
                r.nav,
                _none_to_blank(r.day_change_pct),
                _none_to_blank(r.dist_52w_high_pct),
                _none_to_blank(r.dist_200d_sma_pct),
                _none_to_blank(r.rsi_14),
            ])

        n_rows = len(table)
        n_cols = len(HEADERS)
        self._run_with_retry(
            lambda: ws.resize(rows=max(n_rows + 5, 20), cols=n_cols + 2)
        )

        last_col_letter = "".join(
            ch for ch in rowcol_to_a1(1, n_cols) if ch.isalpha()
        )
        end_a1 = f"{last_col_letter}{n_rows}"
        self._run_with_retry(
            lambda: ws.update(
                f"A1:{end_a1}", table, value_input_option="USER_ENTERED"
            )
        )

        sheet_id = ws._properties["sheetId"]
        requests_payload: list[dict] = []

        # Info banner row (row 1): bold, italic, light fill, merged across columns.
        requests_payload.append({
            "mergeCells": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": n_cols,
                },
                "mergeType": "MERGE_ALL",
            }
        })
        requests_payload.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": n_cols,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True, "italic": True},
                        "backgroundColor": {"red": 0.93, "green": 0.95, "blue": 0.99},
                        "horizontalAlignment": "LEFT",
                        "padding": {"left": 6},
                    }
                },
                "fields": (
                    "userEnteredFormat.textFormat.bold,"
                    "userEnteredFormat.textFormat.italic,"
                    "userEnteredFormat.backgroundColor,"
                    "userEnteredFormat.horizontalAlignment,"
                    "userEnteredFormat.padding"
                ),
            }
        })

        # Header row (row 2): bold + centered + grey fill.
        requests_payload.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": 2,
                    "startColumnIndex": 0,
                    "endColumnIndex": n_cols,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True},
                        "horizontalAlignment": "CENTER",
                        "backgroundColor": {"red": 0.95, "green": 0.95, "blue": 0.97},
                    }
                },
                "fields": (
                    "userEnteredFormat.textFormat.bold,"
                    "userEnteredFormat.horizontalAlignment,"
                    "userEnteredFormat.backgroundColor"
                ),
            }
        })

        # Freeze the banner + header rows.
        requests_payload.append({
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 2},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        })

        # Per-column number formats on data rows (rows 3..N).
        if n_rows > 2:
            for col_idx, fmt in enumerate(_COLUMN_FORMATS):
                if fmt is None:
                    continue
                requests_payload.append({
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 2,
                            "endRowIndex": n_rows,
                            "startColumnIndex": col_idx,
                            "endColumnIndex": col_idx + 1,
                        },
                        "cell": {"userEnteredFormat": {"numberFormat": fmt}},
                        "fields": "userEnteredFormat.numberFormat",
                    }
                })

        self._run_with_retry(
            lambda: ws.spreadsheet.batch_update({"requests": requests_payload})
        )
        log.info(
            "Wrote %d data row(s) to %r (sheet=%s)",
            len(rows), self._worksheet_name, self._spreadsheet_id,
        )


def _none_to_blank(v: float | None) -> object:
    """Render ``None`` as an empty string so Sheets shows a blank cell;
    keep numeric types intact so the column number format applies."""
    return v if v is not None else ""
