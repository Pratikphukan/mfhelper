"""Write the current Groww snapshot to one private Google Sheets tab."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
import json
import re
import threading
import time
import unicodedata
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

import requests

from mfhelper.groww_holdings_import import GrowwHoldingsSnapshot


TAB_NAME = "Current Holdings"
FUND_CODE_MAP_TAB_NAME = "Fund Code Map"
FUND_CODE_MAP_HEADERS = ("Scheme Name", "AMFI Scheme Code")
MAX_FUND_CODE_MAP_ENTRIES = 500
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
MFAPI_SEARCH_URL = "https://api.mfapi.in/mf/search"
MFAPI_CACHE_TTL_SECONDS = 24 * 60 * 60
_MFAPI_CACHE_MAX_ENTRIES = 512
_MFAPI_CACHE: dict[str, tuple[float, tuple[tuple[str, str], ...]]] = {}
_MFAPI_CACHE_LOCK = threading.Lock()


class HoldingsSheetError(ValueError):
    """Safe message for a holdings sheet configuration or write error."""


def parse_fund_code_map(raw: str) -> dict[str, tuple[str, ...]]:
    """Parse a JSON representation of the fund-to-AMFI-code mapping."""
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 64 * 1024:
        raise HoldingsSheetError("The AMFI fund-code mapping is not configured.")
    try:
        entries = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise HoldingsSheetError("The AMFI fund-code mapping is not valid JSON.") from exc
    if not isinstance(entries, list) or not entries or len(entries) > 500:
        raise HoldingsSheetError("The AMFI fund-code mapping must be a non-empty list of funds.")

    pairs: list[tuple[object, object]] = []
    for item in entries:
        if not isinstance(item, dict):
            raise HoldingsSheetError("Each AMFI mapping entry must contain a fund name and code.")
        pairs.append((item.get("name"), item.get("code")))
    return _fund_code_map_from_pairs(pairs)


def parse_fund_code_map_rows(rows: Iterable[Iterable[object]]) -> dict[str, tuple[str, ...]]:
    """Validate the Fund Code Map tab and return its normalized name lookup."""
    values = [list(row) for row in rows]
    if not values:
        raise HoldingsSheetError(
            "The 'Fund Code Map' tab must start with Scheme Name and AMFI Scheme Code headers. "
            "No holdings were changed."
        )

    header = [str(value or "").strip() for value in values[0][:2]]
    if header != list(FUND_CODE_MAP_HEADERS):
        raise HoldingsSheetError(
            "The 'Fund Code Map' tab must start with Scheme Name and AMFI Scheme Code headers. "
            "No holdings were changed."
        )

    pairs: list[tuple[object, object]] = []
    for row_number, row in enumerate(values[1:], start=2):
        name = row[0] if row else ""
        code = row[1] if len(row) > 1 else ""
        if not _cell_text(name) and not _cell_text(code):
            continue
        if not isinstance(name, str) or not name.strip():
            raise HoldingsSheetError(
                f"The 'Fund Code Map' tab has an invalid row {row_number}. "
                "Check that it has a scheme name and a numeric AMFI code. "
                "No holdings were changed."
            )
        try:
            pairs.append((name, _validated_sheet_code(code)))
        except ValueError as exc:
            raise HoldingsSheetError(
                f"The 'Fund Code Map' tab has an invalid row {row_number}. "
                "Check that it has a scheme name and a numeric AMFI code. "
                "No holdings were changed."
            ) from exc
    if len(pairs) > MAX_FUND_CODE_MAP_ENTRIES:
        raise HoldingsSheetError(
            f"The 'Fund Code Map' tab has more than {MAX_FUND_CODE_MAP_ENTRIES} entries. "
            "No holdings were changed."
        )
    return _fund_code_map_from_pairs(pairs)


def _fund_code_map_from_pairs(pairs: Iterable[tuple[object, object]]) -> dict[str, tuple[str, ...]]:
    by_name: dict[str, set[str]] = {}
    for name, code in pairs:
        if not isinstance(name, str) or not name.strip():
            raise HoldingsSheetError("Each AMFI mapping entry must contain a fund name and code.")
        if not isinstance(code, (str, int)) or isinstance(code, bool):
            raise HoldingsSheetError("Each AMFI mapping entry must contain a fund name and code.")
        code = str(code).strip()
        if not code or not code.isdigit() or len(code) > 12:
            raise HoldingsSheetError("An AMFI scheme code in the mapping is invalid.")
        normalized = normalize_scheme_name(name)
        if not normalized:
            raise HoldingsSheetError("A fund name in the AMFI mapping is invalid.")
        by_name.setdefault(normalized, set()).add(code)
    return {name: tuple(sorted(codes)) for name, codes in by_name.items()}


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _validated_sheet_code(value: object) -> str:
    if isinstance(value, bool):
        raise ValueError("boolean is not an AMFI code")
    if isinstance(value, int):
        code = str(value)
    elif isinstance(value, float) and value.is_integer():
        code = str(int(value))
    elif isinstance(value, str):
        code = value.strip()
    else:
        raise ValueError("invalid AMFI code cell")
    if not code or not code.isdigit() or len(code) > 12:
        raise ValueError("invalid AMFI code")
    return code


def normalize_scheme_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value)).casefold()
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def match_scheme_code(
    scheme_name: str,
    code_map: dict[str, tuple[str, ...]],
    *,
    search: Callable[[str], Iterable[tuple[str, str]]] | None = None,
) -> tuple[str, str]:
    """Resolve from private config first, then accept only a unique MFAPI match."""
    matches = code_map.get(normalize_scheme_name(scheme_name), ())
    if len(matches) == 1:
        return matches[0], "exact_config"

    try:
        candidates = (search or _search_mfapi)(scheme_name)
    except Exception:
        candidates = ()
    matched_codes = {
        str(code)
        for code, candidate_name in candidates
        if _same_direct_growth_scheme(scheme_name, candidate_name)
        and str(code).isdigit()
    }
    if len(matched_codes) == 1:
        return next(iter(matched_codes)), "mfapi_search"
    if len(matched_codes) > 1:
        return "", "ambiguous"
    return "", "unmatched"


def _same_direct_growth_scheme(groww_name: str, mfapi_name: str) -> bool:
    """Allow provider wording like 'Direct Plan - Growth Option', not other plans."""
    ignored = {"plan", "option"}
    disallowed = {"regular", "idcw", "dividend", "payout", "reinvestment"}
    groww_parts = normalize_scheme_name(groww_name).split()
    mfapi_parts = normalize_scheme_name(mfapi_name).split()
    if any(part in disallowed for part in groww_parts + mfapi_parts):
        return False
    groww_core = [part for part in groww_parts if part not in ignored]
    mfapi_core = [part for part in mfapi_parts if part not in ignored]
    return (
        "direct" in groww_core
        and "growth" in groww_core
        and "direct" in mfapi_core
        and "growth" in mfapi_core
        and groww_core == mfapi_core
    )


def _search_mfapi(scheme_name: str) -> tuple[tuple[str, str], ...]:
    """Search MFAPI with a short timeout and a 24-hour per-instance cache."""
    key = normalize_scheme_name(scheme_name)
    if not key:
        return ()
    now = time.monotonic()
    with _MFAPI_CACHE_LOCK:
        cached = _MFAPI_CACHE.get(key)
        if cached and now - cached[0] < MFAPI_CACHE_TTL_SECONDS:
            return cached[1]
        if cached:
            _MFAPI_CACHE.pop(key, None)

    try:
        response = requests.get(
            MFAPI_SEARCH_URL,
            params={"q": scheme_name},
            timeout=(2, 4),
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            return ()
        results: list[tuple[str, str]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            code = item.get("schemeCode")
            name = item.get("schemeName")
            if isinstance(code, (str, int)) and not isinstance(code, bool) and isinstance(name, str):
                code_text = str(code)
                if code_text.isdigit() and name.strip():
                    results.append((code_text, name.strip()))
        result_tuple = tuple(results)
    except Exception:
        # Lookup failure is a review state, never a reason to abort a valid import.
        return ()

    with _MFAPI_CACHE_LOCK:
        if len(_MFAPI_CACHE) >= _MFAPI_CACHE_MAX_ENTRIES:
            oldest_key = min(_MFAPI_CACHE, key=lambda item: _MFAPI_CACHE[item][0])
            _MFAPI_CACHE.pop(oldest_key, None)
        _MFAPI_CACHE[key] = (time.monotonic(), result_tuple)
    return result_tuple


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
    names_by_key: dict[str, str] = {}
    for holding in snapshot.holdings:
        key = normalize_scheme_name(holding.scheme_name)
        if key not in names_by_key:
            names_by_key[key] = holding.scheme_name
    unique_names = list(names_by_key.items())
    if unique_names:
        with ThreadPoolExecutor(max_workers=min(4, len(unique_names))) as executor:
            resolved = list(executor.map(lambda pair: match_scheme_code(pair[1], code_map), unique_names))
        resolved_by_key = dict(zip((key for key, _ in unique_names), resolved))
    else:
        resolved_by_key = {}
    for holding in snapshot.holdings:
        code, status = resolved_by_key[normalize_scheme_name(holding.scheme_name)]
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


class FundCodeMapSheetReader:
    """Read the user's private fund-to-AMFI-code map from Google Sheets."""

    def __init__(
        self,
        *,
        spreadsheet_id: str,
        service_account_info: dict[str, object],
        client_factory: Callable[[dict[str, object]], object] | None = None,
        worksheet_name: str = FUND_CODE_MAP_TAB_NAME,
    ) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.service_account_info = service_account_info
        self.client_factory = client_factory or _service_account_client
        self.worksheet_name = worksheet_name

    def read(self) -> dict[str, tuple[str, ...]]:
        try:
            client = self.client_factory(self.service_account_info)
            spreadsheet = client.open_by_key(self.spreadsheet_id)
            try:
                worksheet = spreadsheet.worksheet(self.worksheet_name)
            except Exception as exc:
                if _is_worksheet_missing(exc):
                    raise HoldingsSheetError(
                        "The 'Fund Code Map' tab was not found. Create it with the required headers. "
                        "No holdings were changed."
                    ) from exc
                raise
            rows = worksheet.get("A:B", value_render_option="UNFORMATTED_VALUE")
            return parse_fund_code_map_rows(rows)
        except HoldingsSheetError:
            raise
        except Exception as exc:
            raise HoldingsSheetError(
                "Google Sheets could not read the 'Fund Code Map' tab. "
                "The previous holdings data was preserved."
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
