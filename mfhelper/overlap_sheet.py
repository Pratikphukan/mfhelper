"""Google Sheets writer for the portfolio-weighted overlap report."""

from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
import time
from zoneinfo import ZoneInfo

import gspread
from gspread.utils import rowcol_to_a1

from mfhelper.portfolio_overlap import (
    FundDataIssue,
    PortfolioSnapshot,
    StockExposure,
    UnmappedPosition,
)
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
            worksheet = spreadsheet.worksheet(self._worksheet_name)
        except gspread.WorksheetNotFound:
            log.info("Worksheet %r not found; creating", self._worksheet_name)
            worksheet = spreadsheet.add_worksheet(title=self._worksheet_name, rows=100, cols=20)
        self._worksheet = worksheet
        return worksheet

    @staticmethod
    def _run_with_retry(call):
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                return call()
            except gspread.exceptions.APIError as exc:
                status = getattr(exc.response, "status_code", None) if hasattr(exc, "response") else None
                if attempt < RETRY_ATTEMPTS and (status is None or status in (429, 500, 502, 503, 504)):
                    delay = RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
                    log.info("Sheets API attempt %d/%d failed (HTTP %s); retry in %.1fs",
                             attempt, RETRY_ATTEMPTS, status, delay)
                    time.sleep(delay)
                    continue
                raise

    def write_overlap_report(
        self,
        active_codes: list[str],
        fund_labels: dict[str, str],
        matrix: dict[str, dict[str, float]],
        detailed_overlaps: list[tuple[tuple[str, str], tuple[float, list[dict]]]],
        *,
        portfolio_snapshot: PortfolioSnapshot,
        portfolio_exposures: list[StockExposure],
        fund_data_issues: list[FundDataIssue],
        statement_age_days: int,
        stale_after_days: int = 30,
        now: datetime | None = None,
    ) -> None:
        """Replace the report tab after all source data and calculations are ready."""
        now = now or datetime.now(ZoneInfo("Asia/Kolkata"))
        total_value = portfolio_snapshot.total_current_value
        mapped_value = sum(
            (position.current_value for position in portfolio_snapshot.positions_by_code.values()),
            start=total_value * 0,
        )
        covered_value = sum(
            (portfolio_snapshot.positions_by_code[code].current_value for code in active_codes),
            start=total_value * 0,
        )
        unmapped_value = sum(
            (position.current_value for position in portfolio_snapshot.unmapped_positions),
            start=total_value * 0,
        )
        unavailable_value = sum(
            (issue.current_value for issue in fund_data_issues),
            start=total_value * 0,
        )

        table: list[list[object]] = [
            ["Portfolio-Weighted Mutual Fund Overlap", "", "Report updated (IST)", now.strftime("%Y-%m-%d %H:%M:%S")],
            ["Groww statement date", portfolio_snapshot.statement_date.isoformat(),
             "Statement age (days)", statement_age_days,
             "Freshness", f"STALE (>{stale_after_days} days)" if statement_age_days > stale_after_days else "Current"],
            ["Total reported value (₹)", float(total_value),
             "AMFI-mapped value (₹)", float(mapped_value),
             "Constituent-covered value (₹)", float(covered_value)],
            ["Portfolio coverage", float(covered_value / total_value) if total_value else 0.0,
             "Unmapped value (₹)", float(unmapped_value),
             "Value missing constituents (₹)", float(unavailable_value)],
            ["Tickertape constituent data", "Latest response at report time; provider as-of date is not supplied."],
            [],
            ["Largest Underlying Equity Exposures (estimated from reported values)"],
            ["Stock / Company", "Ticker", "Estimated exposure (₹)", "% of reported portfolio",
             "Funds contributing"],
        ]
        exposure_section_row = 7
        exposure_header_row = len(table)
        if portfolio_exposures:
            for exposure in portfolio_exposures:
                table.append([
                    exposure.company_name,
                    exposure.ticker,
                    float(exposure.estimated_value),
                    float(exposure.portfolio_pct / 100),
                    ", ".join(exposure.fund_names),
                ])
        else:
            table.append(["No stock exposure could be calculated."])

        table.append([])
        unmapped_section_row = len(table) + 1
        table.append(["Current Holdings Without a Resolved AMFI Code"])
        table.append(["Fund name", "Current value (₹)", "Reason"])
        unmapped_header_row = len(table)
        if portfolio_snapshot.unmapped_positions:
            for position in portfolio_snapshot.unmapped_positions:
                table.append([position.name, float(position.current_value), position.reason])
        else:
            table.append(["None"])

        table.append([])
        issue_section_row = len(table) + 1
        table.append(["Funds Without Constituent Data"])
        table.append(["AMFI code", "Fund name", "Current value (₹)", "Reason"])
        issue_header_row = len(table)
        if fund_data_issues:
            for issue in fund_data_issues:
                table.append([issue.code, issue.name, float(issue.current_value), issue.reason])
        else:
            table.append(["None"])

        table.append([])
        table.append(["Pairwise Fund Overlap Matrix (%)"])
        matrix_title_row = len(table)
        if active_codes:
            header_row = ["Fund name / AMFI code"] + [
                f"{fund_labels[code]} [{code}]" for code in active_codes
            ]
            table.append(header_row)
            matrix_header_row = len(table)
            matrix_start_row = matrix_header_row
            for code_a in active_codes:
                table.append([
                    f"{fund_labels[code_a]} [{code_a}]",
                    *[matrix[code_a][code_b] / 100.0 for code_b in active_codes],
                ])
            matrix_end_row = len(table)
        else:
            header_row = ["No fund constituent data was available."]
            table.append(header_row)
            matrix_header_row = len(table)
            matrix_start_row = matrix_end_row = len(table)

        table.append([])
        table.append(["Detailed Pairwise Stock Overlap Breakdown (>10.0% overlap)"])
        detailed_pairs_rows: list[int] = []
        detailed_header_rows: list[int] = []
        for pair, (overlap, details) in detailed_overlaps:
            if overlap < 10.0:
                continue
            code_a, code_b = pair
            table.append([f"Pair: '{fund_labels[code_a]}' vs '{fund_labels[code_b]}'",
                          f"Total overlap: {overlap:.2f}%"])
            detailed_pairs_rows.append(len(table))
            table.append(["Stock / Holding Name", "Allocation in A %", "Allocation in B %",
                          "Overlap Contribution %"])
            detailed_header_rows.append(len(table))
            target = 0.90 * overlap
            cumulative = 0.0
            top_details: list[dict] = []
            remaining: list[dict] = []
            for detail in details:
                if cumulative < target:
                    top_details.append(detail)
                    cumulative += detail["intersection"]
                else:
                    remaining.append(detail)
            for detail in top_details:
                table.append([
                    detail["company_name"],
                    detail["alloc_a"] / 100.0,
                    detail["alloc_b"] / 100.0,
                    detail["intersection"] / 100.0,
                ])
            if remaining:
                table.append(["Other overlapping stocks: " + ", ".join(item["company_name"] for item in remaining)])
            table.append([])

        # Construct the report before clearing the old one. A malformed input or
        # calculation failure therefore cannot erase the previous report.
        worksheet = self._connect()
        self._run_with_retry(worksheet.clear)
        row_count = len(table)
        column_count = max(max((len(row) for row in table), default=1), 10)
        self._run_with_retry(lambda: worksheet.resize(
            rows=max(row_count + 20, 100), cols=column_count + 5
        ))
        last_col = rowcol_to_a1(1, column_count)[:-1]
        self._run_with_retry(lambda: worksheet.update(
            f"A1:{last_col}{row_count}", table, value_input_option="USER_ENTERED"
        ))

        sheet_id = worksheet._properties["sheetId"]
        requests_payload: list[dict] = [{"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": row_count,
                      "startColumnIndex": 0, "endColumnIndex": column_count},
            "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP",
                                            "verticalAlignment": "TOP"}},
            "fields": "userEnteredFormat.wrapStrategy,userEnteredFormat.verticalAlignment",
        }}]

        def style_row(row_index: int, column_count_for_style: int, *, background=None) -> None:
            fmt: dict = {"textFormat": {"bold": True}}
            fields = ["userEnteredFormat.textFormat.bold"]
            if background:
                fmt["backgroundColor"] = background
                fields.append("userEnteredFormat.backgroundColor")
            requests_payload.append({"repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": row_index - 1,
                          "endRowIndex": row_index, "startColumnIndex": 0,
                          "endColumnIndex": column_count_for_style},
                "cell": {"userEnteredFormat": fmt}, "fields": ",".join(fields),
            }})

        style_row(1, 1)
        for row_index in (exposure_section_row, unmapped_section_row, issue_section_row, matrix_title_row):
            style_row(row_index, column_count, background={"red": 0.91, "green": 0.94, "blue": 0.98})
        style_row(exposure_header_row, 5, background={"red": 0.95, "green": 0.95, "blue": 0.97})
        style_row(unmapped_header_row, 3, background={"red": 0.95, "green": 0.95, "blue": 0.97})
        style_row(issue_header_row, 4, background={"red": 0.95, "green": 0.95, "blue": 0.97})

        requests_payload.append({"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 3, "endRowIndex": 4,
                      "startColumnIndex": 1, "endColumnIndex": 2},
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "0.00%"}}},
            "fields": "userEnteredFormat.numberFormat",
        }})

        if portfolio_exposures:
            requests_payload.append({"repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": exposure_header_row,
                          "endRowIndex": exposure_header_row + len(portfolio_exposures),
                          "startColumnIndex": 2, "endColumnIndex": 3},
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}}},
                "fields": "userEnteredFormat.numberFormat",
            }})
            requests_payload.append({"repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": exposure_header_row,
                          "endRowIndex": exposure_header_row + len(portfolio_exposures),
                          "startColumnIndex": 3, "endColumnIndex": 4},
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "0.00%"}}},
                "fields": "userEnteredFormat.numberFormat",
            }})

        if active_codes:
            style_row(matrix_header_row, len(header_row), background={"red": 0.95, "green": 0.95, "blue": 0.97})
            requests_payload.append({"repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": matrix_start_row,
                          "endRowIndex": matrix_end_row, "startColumnIndex": 1,
                          "endColumnIndex": len(header_row)},
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "0.00%"},
                                                "horizontalAlignment": "CENTER"}},
                "fields": "userEnteredFormat.numberFormat,userEnteredFormat.horizontalAlignment",
            }})

        for row_index in detailed_pairs_rows:
            style_row(row_index, 4, background={"red": 0.99, "green": 0.93, "blue": 0.92})
        for row_index in detailed_header_rows:
            style_row(row_index, 4, background={"red": 0.95, "green": 0.95, "blue": 0.95})
            requests_payload.append({"repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": row_index,
                          "endRowIndex": min(row_index + 9, row_count), "startColumnIndex": 1,
                          "endColumnIndex": 4},
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "0.00%"}}},
                "fields": "userEnteredFormat.numberFormat",
            }})

        requests_payload.append({"autoResizeDimensions": {
            "dimensions": {"sheetId": sheet_id, "dimension": "ROWS",
                           "startIndex": 0, "endIndex": row_count},
        }})

        if requests_payload:
            self._run_with_retry(lambda: worksheet.spreadsheet.batch_update({"requests": requests_payload}))
        log.info("Successfully updated '%s' tab in Google Sheets.", self._worksheet_name)
