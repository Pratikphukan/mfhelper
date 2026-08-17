"""Google Sheets writer for the Portfolio Overlap report tab.

Creates a fresh, formatted 'Portfolio Overlap' tab in your Google Sheet,
populating a pairwise overlap percentage grid and a detailed stock-by-stock
analysis for high-overlap pairs.
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

OVERLAP_TAB_DEFAULT = "Portfolio Overlap"
RETRY_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = 2.0


class OverlapSheetWriter:
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
                cols=20,
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

    def write_overlap_report(
        self,
        active_codes: list[str],
        fund_labels: dict[str, str],
        matrix: dict[str, dict[str, float]],
        detailed_overlaps: list[tuple[tuple[str, str], tuple[float, list[dict]]]],
    ) -> None:
        """Write the complete matrix and detailed overlap breakdown to the Sheet."""
        ws = self._connect()
        self._run_with_retry(ws.clear)

        table = []
        
        # 1. Title Row
        table.append(["Mutual Fund Portfolio Overlap Matrix (%)", "", "", "Last updated (IST):", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
        table.append([]) # Blank spacer
        
        # 2. Build the Matrix Headers & Rows
        header_row = ["Fund Name / Code"]
        for code in active_codes:
            header_row.append(fund_labels[code])
        table.append(header_row)
        
        matrix_start_row = len(table) # 1-indexed (row 3 is index 2)
        
        for code_a in active_codes:
            row = [fund_labels[code_a]]
            for code_b in active_codes:
                val = matrix[code_a][code_b]
                # Scale from percent to fractional decimal so Google Sheets formatting displays it nicely as %
                row.append(val / 100.0)
            table.append(row)
            
        matrix_end_row = len(table)
        
        # 3. Add spacers and then Detailed analysis
        table.append([])
        table.append([])
        table.append(["Detailed Pairwise Stock Overlap Breakdown (>10.0% Overlap)"])
        table.append([])
        
        # We will keep track of specific rows we want to format nicely
        detailed_headers_indices = []
        detailed_pairs_indices = []
        
        for pair, (overlap, details) in detailed_overlaps:
            if overlap < 10.0:
                continue
            
            code_a, code_b = pair
            name_a = fund_labels[code_a]
            name_b = fund_labels[code_b]
            
            # Sub-header: Pair names & overall overlap
            detailed_pairs_indices.append(len(table) + 1)
            table.append([f"Pair: '{name_a}' vs '{name_b}'", f"Total Overlap: {overlap:.2f}%"])
            
            # Stock columns headers
            detailed_headers_indices.append(len(table) + 1)
            table.append(["Stock / Holding Name", "Allocation in A %", "Allocation in B %", "Overlap Contribution %"])
            
            # Write top overlapping stocks
            for d in details[:8]:
                table.append([
                    d["company_name"],
                    d["alloc_a"] / 100.0,
                    d["alloc_b"] / 100.0,
                    d["intersection"] / 100.0
                ])
            if len(details) > 8:
                table.append([f"...and {len(details) - 8} more overlapping stock(s)"])
                
            table.append([]) # Spacer row between pairs
            
        # Ensure sheet size fits the output
        n_rows = len(table)
        n_cols = len(header_row)
        max_cols = max(n_cols, 10)
        
        self._run_with_retry(lambda: ws.resize(rows=max(n_rows + 20, 100), cols=max_cols + 5))
        
        # Write values
        last_col_letter = rowcol_to_a1(1, max_cols)[:-1]
        self._run_with_retry(
            lambda: ws.update(
                f"A1:{last_col_letter}{n_rows}",
                table,
                value_input_option="USER_ENTERED"
            )
        )
        
        # Apply standard, atomic sheets formatting via batch_update
        sheet_id = ws._properties["sheetId"]
        requests_payload: list[dict] = []
        
        # Bold Main Titles
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
        
        # Bold Overlap Matrix Headers
        requests_payload.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 2,
                    "endRowIndex": 3,
                    "startColumnIndex": 0,
                    "endColumnIndex": len(header_row),
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
        
        # Format Matrix Data cells as Percentage
        requests_payload.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": matrix_start_row,
                    "endRowIndex": matrix_end_row,
                    "startColumnIndex": 1,
                    "endColumnIndex": len(header_row),
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
        
        # Bold the fund names in column 1 of the matrix
        requests_payload.append({
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": matrix_start_row,
                    "endRowIndex": matrix_end_row,
                    "startColumnIndex": 0,
                    "endColumnIndex": 1,
                },
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold",
            }
        })
        
        # Format Detailed Breakdowns
        for r_idx in detailed_pairs_indices:
            # Pair label row: make bold and light red/orange highlights
            requests_payload.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": r_idx - 1,
                        "endRowIndex": r_idx,
                        "startColumnIndex": 0,
                        "endColumnIndex": 4,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {"bold": True},
                            "backgroundColor": {"red": 0.99, "green": 0.93, "blue": 0.92},
                        }
                    },
                    "fields": "userEnteredFormat.textFormat.bold,userEnteredFormat.backgroundColor",
                }
            })
            
        for r_idx in detailed_headers_indices:
            # Headers row: bold, centered
            requests_payload.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": r_idx - 1,
                        "endRowIndex": r_idx,
                        "startColumnIndex": 0,
                        "endColumnIndex": 4,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {"bold": True, "fontSize": 9},
                            "horizontalAlignment": "CENTER",
                            "backgroundColor": {"red": 0.95, "green": 0.95, "blue": 0.95},
                        }
                    },
                    "fields": "userEnteredFormat.textFormat.bold,userEnteredFormat.textFormat.fontSize,userEnteredFormat.horizontalAlignment,userEnteredFormat.backgroundColor",
                }
            })
            
            # Format the stock percentage rows under this header as %
            requests_payload.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": r_idx,
                        "endRowIndex": r_idx + 8, # top 8 stocks
                        "startColumnIndex": 1,
                        "endColumnIndex": 4,
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

        self._run_with_retry(lambda: ws.spreadsheet.batch_update({"requests": requests_payload}))
        log.info("Successfully updated '%s' tab in Google Sheets.", self._worksheet_name)
