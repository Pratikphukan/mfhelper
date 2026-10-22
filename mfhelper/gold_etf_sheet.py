"""Google Sheets writer for the Gold ETFs Analytics tab.

Creates a fresh, formatted 'Gold ETFs Analytics' tab in your Google Sheet,
populating performance CAGRs, volatility SDs, Sharpe/Sortino/Calmar ratios,
and max drawdowns across all tracked Indian Gold ETFs.
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

GOLD_ETF_TAB_DEFAULT = "Gold ETFs Analytics"
RETRY_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = 2.0

HEADERS = (
    "ETF Name",
    "Ticker",
    "AMFI Code",
    "1Y Abs %",
    "3Y CAGR %",
    "5Y CAGR %",
    "Inception CAGR %",
    "Ann. SD (3Y) %",
    "Sharpe (3Y)",
    "Sortino (3Y)",
    "Calmar (3Y)",
    "Max DD (3Y) %",
    "Last Updated (IST)",
)


class GoldEtfSheetWriter:
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
                rows=50,
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

    def write_table(self, payloads: list[dict]) -> None:
        """Replace the 'Gold ETFs Analytics' tab with a fresh header + payload rows."""
        ws = self._connect()
        self._run_with_retry(ws.clear)

        table = [list(HEADERS)]
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for p in payloads:
            tr = p.get("trailing_returns") or {}
            risk = p.get("risk") or {}
            ra = p.get("risk_adjusted") or {}

            def fmt_pct(val):
                return val / 100.0 if isinstance(val, (int, float)) else ""

            def fmt_num(val):
                return val if isinstance(val, (int, float)) else ""

            row = [
                p.get("etf_name", ""),
                p.get("ticker", ""),
                p.get("code", ""),
                fmt_pct(tr.get("1y_absolute_pct")),
                fmt_pct(tr.get("3y_cagr_pct")),
                fmt_pct(tr.get("5y_cagr_pct")),
                fmt_pct(tr.get("since_inception_cagr_pct")),
                fmt_pct(risk.get("sd_3y_annualized_pct")),
                fmt_num(ra.get("sharpe_3y")),
                fmt_num(ra.get("sortino_3y")),
                fmt_num(ra.get("calmar_3y")),
                fmt_pct(risk.get("max_drawdown_pct")),
                now_str,
            ]
            table.append(row)

        n_rows = len(table)
        n_cols = len(HEADERS)
        self._run_with_retry(lambda: ws.resize(rows=max(n_rows + 5, 20), cols=n_cols + 2))

        last_col = rowcol_to_a1(1, n_cols)[:-1]
        end_a1 = f"{last_col}{n_rows}"
        self._run_with_retry(lambda: ws.update(f"A1:{end_a1}", table, value_input_option="USER_ENTERED"))

        # Batch format styling
        sheet_id = ws._properties["sheetId"]
        requests_payload: list[dict] = []

        # Header formatting
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
                        "backgroundColor": {"red": 0.98, "green": 0.94, "blue": 0.85}, # Soft Gold fill
                    }
                },
                "fields": "userEnteredFormat.textFormat.bold,userEnteredFormat.horizontalAlignment,userEnteredFormat.backgroundColor",
            }
        })

        # Format Percentages
        pct_cols = [3, 4, 5, 6, 7, 11]
        for c in pct_cols:
            requests_payload.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": n_rows,
                        "startColumnIndex": c,
                        "endColumnIndex": c + 1,
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

        # Format Ratios
        ratio_cols = [8, 9, 10]
        for c in ratio_cols:
            requests_payload.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": n_rows,
                        "startColumnIndex": c,
                        "endColumnIndex": c + 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "numberFormat": {"type": "NUMBER", "pattern": "0.00"},
                            "horizontalAlignment": "CENTER"
                        }
                    },
                    "fields": "userEnteredFormat.numberFormat,userEnteredFormat.horizontalAlignment",
                }
            })

        # Center tickers and codes
        for c in [1, 2, 12]:
            requests_payload.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": n_rows,
                        "startColumnIndex": c,
                        "endColumnIndex": c + 1,
                    },
                    "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
                    "fields": "userEnteredFormat.horizontalAlignment",
                }
            })

        self._run_with_retry(lambda: ws.spreadsheet.batch_update({"requests": requests_payload}))
        log.info("Successfully updated '%s' tab in Google Sheets.", self._worksheet_name)
