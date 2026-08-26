"""Google Sheets writer for the Combined Portfolio Allocation tab.

Creates a fresh, formatted 'Combined Allocation' tab in your Google Sheet,
populating your consolidated sector distributions and top 15 stock holdings.
"""

from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
import time

import gspread
from gspread.utils import rowcol_to_a1

from mfhelper.sheets import _load_credentials

log = logging.getLogger(__name__)

ALLOCATION_TAB_DEFAULT = "Combined Allocation"
RETRY_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = 2.0


class PortfolioMapSheetWriter:
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
                rows=100,
                cols=10,
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

    def write_allocation_report(
        self,
        sectors_sorted: list[tuple[str, float]],
        stocks_sorted: list[dict],
    ) -> None:
        """Write consolidated sectors and top stocks side-by-side into the sheet."""
        ws = self._connect()
        self._run_with_retry(ws.clear)

        table = []
        
        # 1. Main Titles
        table.append(["Consolidated Portfolio Asset Map", "", "", "", "Last updated (IST):", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
        table.append([]) # spacer
        
        # 2. Side-by-side Table Headers
        # Left Table: Sectors | Right Table: Top Stock Holdings (Top 15)
        headers = [
            "Consolidated Industry Sector", "Portfolio Weight %", "", 
            "Consolidated Stock Holding", "Ticker", "Combined Weight %"
        ]
        table.append(headers)
        
        data_start_row = len(table)
        
        # Merge sector and stock lists row-by-row
        row_limit = max(len(sectors_sorted), len(stocks_sorted), 15)
        for idx in range(row_limit):
            row = ["", "", "", "", "", ""]
            
            # Populate Sector columns (0, 1)
            if idx < len(sectors_sorted):
                sec_name, sec_weight = sectors_sorted[idx]
                row[0] = sec_name
                row[1] = sec_weight / 100.0  # scale for sheets % formatting
                
            # Spacer column (2) remains blank
            
            # Populate Stock columns (3, 4, 5)
            if idx < len(stocks_sorted):
                st = stocks_sorted[idx]
                row[3] = st["company_name"]
                row[4] = st.get("ticker") or ""
                row[5] = st["combined_weight"] / 100.0  # scale for sheets % formatting
                
            table.append(row)
            
        data_end_row = len(table)

        # Explicitly resize sheet
        n_rows = len(table)
        self._run_with_retry(lambda: ws.resize(rows=max(n_rows + 10, 40), cols=10))

        # Write data grid
        self._run_with_retry(
            lambda: ws.update(
                f"A1:F{n_rows}",
                table,
                value_input_option="USER_ENTERED"
            )
        )

        # Apply formatting
        sheet_id = ws._properties["sheetId"]
        requests_payload: list[dict] = []

        # Format Titles
        requests_payload.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": 1,
                },
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "fontSize": 12}}},
                "fields": "userEnteredFormat.textFormat.bold,userEnteredFormat.textFormat.fontSize",
            }
        })

        # Format Side-by-side Table Headers
        requests_payload.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 2,
                    "endRowIndex": 3,
                    "startColumnIndex": 0,
                    "endColumnIndex": 6,
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

        # Format Sector Weight (Col B/Index 1) as %
        requests_payload.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": data_start_row,
                    "endRowIndex": data_end_row,
                    "startColumnIndex": 1,
                    "endColumnIndex": 2,
                },
                "cell": {
                    "userEnteredFormat": {
                        "numberFormat": {"type": "NUMBER", "pattern": "0.00%"},
                        "horizontalAlignment": "CENTER"
                    }
                },
                "fields": "userEnteredFormat.numberFormat,userEnteredFormat.horizontalAlignment",
            }
        })

        # Format Stock Weight (Col F/Index 5) as %
        requests_payload.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": data_start_row,
                    "endRowIndex": data_end_row,
                    "startColumnIndex": 5,
                    "endColumnIndex": 6,
                },
                "cell": {
                    "userEnteredFormat": {
                        "numberFormat": {"type": "NUMBER", "pattern": "0.00%"},
                        "horizontalAlignment": "CENTER"
                    }
                },
                "fields": "userEnteredFormat.numberFormat,userEnteredFormat.horizontalAlignment",
            }
        })

        # Center tickers (Col E/Index 4)
        requests_payload.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": data_start_row,
                    "endRowIndex": data_end_row,
                    "startColumnIndex": 4,
                    "endColumnIndex": 5,
                },
                "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
                "fields": "userEnteredFormat.horizontalAlignment",
            }
        })

        self._run_with_retry(lambda: ws.spreadsheet.batch_update({"requests": requests_payload}))
        log.info("Successfully updated '%s' tab in Google Sheets.", self._worksheet_name)
