"""Write the current Groww snapshot to one private Google Sheets tab."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import json
import re
import unicodedata
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

from mfhelper.groww_holdings_import import GrowwHoldingsSnapshot


TAB_NAME = "Current Holdings"
HEADERS = (
    "Scheme Name",
    "AMFI Scheme Code",
    "AMFI Code Match",
    "Category",
    "Sub-category",
    "Folio No.",
    "Units",
    "Invested Value",
    "Current Value",
    "Returns",
    "XIRR",
    "Statement Date",
    "Last Updated",
)
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


class HoldingsSheetError(ValueError):
    """Safe message for a holdings sheet configuration or write error."""


def parse_fund_code_map(raw: str) -> dict[str, tuple[str, ...]]:
    """Parse the minimal JSON list copied from the user's private funds.yaml."""
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 64 * 1024:
        raise HoldingsSheetError("The AMFI fund-code mapping is not configured.")
    try:
        entries = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise HoldingsSheetError("The AMFI fund-code mapping is not valid JSON.") from exc
    if not isinstance(entries, list) or not entries or len(entries) > 500:
        raise HoldingsSheetError("The AMFI fund-code mapping must be a non-empty list of funds.")

    by_name: dict[str, set[str]] = {}
    for item in entries:
        if not isinstance(item, dict):
            raise HoldingsSheetError("Each AMFI mapping entry must contain a fund name and code.")
        name = item.get("name")
        code = item.get("code")
        if not isinstance(name, str) or not name.strip() or not isinstance(code, (str, int)):
            raise HoldingsSheetError("Each AMFI mapping entry must contain a fund name and code.")
        code = str(code).strip()
        if not code or not code.isdigit() or len(code) > 12:
            raise HoldingsSheetError("An AMFI scheme code in the mapping is invalid.")
        normalized = normalize_scheme_name(name)
        if not normalized:
            raise HoldingsSheetError("A fund name in the AMFI mapping is invalid.")
        by_name.setdefault(normalized, set()).add(code)
    return {name: tuple(sorted(codes)) for name, codes in by_name.items()}


def normalize_scheme_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value)).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def match_scheme_code(
    scheme_name: str,
    code_map: dict[str, tuple[str, ...]],
) -> tuple[str, str]:
    """Return an AMFI code only for a unique normalized fund-name match."""
    matches = code_map.get(normalize_scheme_name(scheme_name), ())
    if len(matches) == 1:
        return matches[0], "Matched"
    return "", "Needs review"


def make_sheet_values(
    snapshot: GrowwHoldingsSnapshot,
    code_map: dict[str, tuple[str, ...]],
    *,
    imported_at: datetime | None = None,
) -> tuple[list[list[object]], int]:
    """Build a complete replacement table and return it with the unmatched count."""
    updated = (imported_at or datetime.now(ZoneInfo("Asia/Kolkata"))).astimezone(
        ZoneInfo("Asia/Kolkata")
    )
    timestamp = updated.strftime("%Y-%m-%d %H:%M:%S")
    statement_date = snapshot.statement_date.isoformat()
    values: list[list[object]] = [list(HEADERS)]
    unmatched = 0
    for holding in snapshot.holdings:
        code, status = match_scheme_code(holding.scheme_name, code_map)
        if not code:
            unmatched += 1
        values.append([
            holding.scheme_name,
            code,
            status,
            holding.category,
            holding.sub_category,
            holding.folio_no,
            float(holding.units),
            float(holding.invested_value),
            float(holding.current_value),
            float(holding.returns),
            float(holding.xirr) if holding.xirr is not None else "",
            statement_date,
            timestamp,
        ])
    return values, unmatched


class CurrentHoldingsSheetWriter:
    def __init__(
        self,
        *,
        spreadsheet_id: str,
        service_account_info: dict[str, object],
        client_factory: Callable[[dict[str, object]], object] | None = None,
        worksheet_name: str = TAB_NAME,
    ) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.service_account_info = service_account_info
        self.client_factory = client_factory or _service_account_client
        self.worksheet_name = worksheet_name

    def replace(self, values: list[list[object]]) -> None:
        if not values or values[0] != list(HEADERS) or any(len(row) != len(HEADERS) for row in values):
            raise HoldingsSheetError("The holdings table has an unexpected structure. Nothing was written.")

        try:
            client = self.client_factory(self.service_account_info)
            spreadsheet = client.open_by_key(self.spreadsheet_id)
            try:
                worksheet = spreadsheet.worksheet(self.worksheet_name)
            except Exception as exc:
                if not _is_worksheet_missing(exc):
                    raise
                worksheet = spreadsheet.add_worksheet(
                    title=self.worksheet_name,
                    rows=max(1000, len(values)),
                    cols=len(HEADERS),
                )

            existing_header = worksheet.row_values(1)
            if existing_header and existing_header != list(HEADERS):
                raise HoldingsSheetError(
                    "The 'Current Holdings' tab already has a different layout. It was left unchanged."
                )
            _atomic_replace(worksheet, spreadsheet, values)
        except HoldingsSheetError:
            raise
        except Exception as exc:
            raise HoldingsSheetError(
                "Google Sheets could not update the current holdings. The previous data was preserved."
            ) from exc


def _service_account_client(info: dict[str, object]):
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as exc:  # pragma: no cover - deployment packaging guard
        raise HoldingsSheetError("Google Sheets support is not installed on this service.") from exc
    credentials = Credentials.from_service_account_info(info, scopes=[SHEETS_SCOPE])
    return gspread.authorize(credentials)


def _is_worksheet_missing(exc: Exception) -> bool:
    try:
        import gspread
    except ImportError:
        return False
    return isinstance(exc, gspread.WorksheetNotFound)


def _atomic_replace(worksheet: object, spreadsheet: object, values: list[list[object]]) -> None:
    sheet_id = worksheet.id
    old_row_count = int(getattr(worksheet, "row_count", len(values)))
    old_column_count = int(getattr(worksheet, "col_count", len(HEADERS)))
    row_count = max(old_row_count, len(values))
    column_count = max(old_column_count, len(HEADERS))
    rows = [{"values": [_cell_data(value) for value in row]} for row in values]
    rows.extend({"values": [{} for _ in HEADERS]} for _ in range(row_count - len(values)))
    requests = [
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"rowCount": row_count, "columnCount": column_count},
                },
                "fields": "gridProperties(rowCount,columnCount)",
            }
        },
        {
            "updateCells": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "startColumnIndex": 0,
                    "endRowIndex": row_count,
                    "endColumnIndex": len(HEADERS),
                },
                "rows": rows,
                "fields": "userEnteredValue",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": len(HEADERS),
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True},
                        "backgroundColor": {"red": 0.89, "green": 0.93, "blue": 0.98},
                    }
                },
                "fields": "userEnteredFormat(textFormat,backgroundColor)",
            }
        },
        _number_format_request(sheet_id, 6, 10, "#,##0.00"),
        _number_format_request(sheet_id, 10, 11, "0.00%"),
    ]
    spreadsheet.batch_update({"requests": requests})


def _cell_data(value: object) -> dict[str, object]:
    if isinstance(value, bool):
        return {"userEnteredValue": {"boolValue": value}}
    if isinstance(value, (int, float, Decimal)):
        return {"userEnteredValue": {"numberValue": float(value)}}
    if value is None or value == "":
        return {}
    return {"userEnteredValue": {"stringValue": str(value)}}


def _number_format_request(sheet_id: int, start_column: int, end_column: int, pattern: str) -> dict[str, object]:
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 1,
                "startColumnIndex": start_column,
                "endColumnIndex": end_column,
            },
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": pattern}}},
            "fields": "userEnteredFormat.numberFormat",
        }
    }
