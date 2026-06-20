"""Google Sheets writer for the analytics report tab.

Distinct from :mod:`mfhelper.sheets` (which is hand-rolled for the wide,
two-row-merged-header daily NAV layout). This is a much simpler, single-
row-header table:

    | Fund Name | Scheme Code | 1Y % | 3Y % | 5Y % | 7Y % | 10Y % | SD % | Sharpe | Sortino | Expense % | Last Updated |
    |  ...      |   ...       | ...  | ...  | ...  | ...  | ...   | ...  | ...    | ...     | ...       | ...          |

The tab is overwritten on every run. No history is kept on this tab --
for trends in NAV/risk over time, the daily NAV tab and rolling-window
metrics serve that purpose.

OAuth is shared with the daily NAV writer (same ``credentials.json`` /
``token.json`` files), via the existing ``_load_credentials`` helper.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import logging
import time

import gspread
from gspread.utils import rowcol_to_a1

from mfhelper.sheets import _load_credentials

log = logging.getLogger(__name__)

ANALYTICS_TAB_DEFAULT = "Fund Analytics"

HEADERS = (
    "Fund Name",
    "Scheme Code",
    "1Y %",
    "3Y CAGR %",
    "5Y CAGR %",
    "7Y CAGR %",
    "10Y CAGR %",
    "SD %",
    "Sharpe",
    "Sortino",
    "Expense %",
    "Last Updated (IST)",
)

_PERCENT_FMT = {"type": "NUMBER", "pattern": '0.00"%"'}
_RATIO_FMT = {"type": "NUMBER", "pattern": "0.00"}
_TEXT_FMT = {"type": "TEXT"}

# Per-column number formats, aligned with HEADERS above.
_COLUMN_FORMATS = (
    None,           # Fund Name (text)
    None,           # Scheme Code (text)
    _PERCENT_FMT,   # 1Y
    _PERCENT_FMT,   # 3Y
    _PERCENT_FMT,   # 5Y
    _PERCENT_FMT,   # 7Y
    _PERCENT_FMT,   # 10Y
    _PERCENT_FMT,   # SD
    _RATIO_FMT,     # Sharpe
    _RATIO_FMT,     # Sortino
    _PERCENT_FMT,   # Expense
    None,           # Last Updated
)

RETRY_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = 2.0


@dataclass(frozen=True)
class AnalyticsRow:
    fund_name: str
    scheme_code: str
    return_1y_abs_pct: float | None
    cagr_3y_pct: float | None
    cagr_5y_pct: float | None
    cagr_7y_pct: float | None
    cagr_10y_pct: float | None
    sd_pct: float | None
    sharpe: float | None
    sortino: float | None
    expense_pct: float | None
    last_updated_ist: datetime

    def to_cells(self) -> list:
        # ``""`` (empty string) renders as a blank cell in Sheets, which is
        # what we want for unavailable metrics. Numeric cells preserve their
        # native type so the per-column number format applies.
        def fmt_pct(v: float | None) -> object:
            return v if v is not None else ""

        def fmt_ratio(v: float | None) -> object:
            return v if v is not None else ""

        return [
            self.fund_name,
            self.scheme_code,
            fmt_pct(self.return_1y_abs_pct),
            fmt_pct(self.cagr_3y_pct),
            fmt_pct(self.cagr_5y_pct),
            fmt_pct(self.cagr_7y_pct),
            fmt_pct(self.cagr_10y_pct),
            fmt_pct(self.sd_pct),
            fmt_ratio(self.sharpe),
            fmt_ratio(self.sortino),
            fmt_pct(self.expense_pct),
            self.last_updated_ist.strftime("%Y-%m-%d %H:%M:%S"),
        ]


class AnalyticsSheetWriter:
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
                rows=max(50, 10),
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
                status = getattr(exc.response, "status_code", None) if hasattr(exc, "response") else None
                if attempt < RETRY_ATTEMPTS and (status is None or status in (429, 500, 502, 503, 504)):
                    sleep_s = RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
                    log.info(
                        "Sheets API attempt %d/%d failed (HTTP %s); retry in %.1fs",
                        attempt, RETRY_ATTEMPTS, status, sleep_s,
                    )
                    time.sleep(sleep_s)
                    continue
                raise

    def write_table(self, rows: list[AnalyticsRow]) -> None:
        """Replace the entire tab with a fresh header + ``rows`` body."""
        ws = self._connect()

        # Clear everything first so we don't leave stale rows from a longer
        # previous run if the new fund list is shorter.
        self._run_with_retry(ws.clear)

        # Build the table: header + data rows.
        table = [list(HEADERS)]
        for r in rows:
            table.append(r.to_cells())

        # Ensure the sheet has enough rows/cols. gspread auto-grows on
        # update, but we resize explicitly so cleared formatting is reset.
        n_rows = len(table)
        n_cols = len(HEADERS)
        self._run_with_retry(lambda: ws.resize(rows=max(n_rows + 5, 20), cols=n_cols + 2))

        last_col = rowcol_to_a1(1, n_cols)[:-1]  # letter only
        end_a1 = f"{last_col}{n_rows}"
        self._run_with_retry(lambda: ws.update(f"A1:{end_a1}", table, value_input_option="USER_ENTERED"))

        # Header formatting + per-column number formats. We do this in a
        # single batch_update for efficiency and atomicity.
        sheet_id = ws._properties["sheetId"]  # gspread doesn't expose this cleanly otherwise
        requests_payload: list[dict] = []

        # Header row: bold, centered, light fill, frozen.
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
                        "textFormat": {"bold": True},
                        "horizontalAlignment": "CENTER",
                        "backgroundColor": {"red": 0.95, "green": 0.95, "blue": 0.97},
                    }
                },
                "fields": "userEnteredFormat.textFormat.bold,userEnteredFormat.horizontalAlignment,userEnteredFormat.backgroundColor",
            }
        })
        requests_payload.append({
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 1},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        })

        # Per-column number formats on the data rows only.
        if n_rows > 1:
            for col_idx, fmt in enumerate(_COLUMN_FORMATS):
                if fmt is None:
                    continue
                requests_payload.append({
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "endRowIndex": n_rows,
                            "startColumnIndex": col_idx,
                            "endColumnIndex": col_idx + 1,
                        },
                        "cell": {"userEnteredFormat": {"numberFormat": fmt}},
                        "fields": "userEnteredFormat.numberFormat",
                    }
                })

        self._run_with_retry(lambda: ws.spreadsheet.batch_update({"requests": requests_payload}))
        log.info(
            "Wrote %d data row(s) to %r (sheet=%s)",
            len(rows), self._worksheet_name, self._spreadsheet_id,
        )
