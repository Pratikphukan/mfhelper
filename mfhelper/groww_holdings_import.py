"""Read the detailed holdings table from a Groww XLSX export."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
import math
import re
from typing import Iterable


MAX_XLSX_BYTES = 25 * 1024 * 1024
MAX_WORKSHEETS = 10
MAX_SCAN_ROWS = 5000
MAX_SCAN_COLUMNS = 100


class GrowwImportError(ValueError):
    """Safe message for an unsupported or invalid Groww workbook."""


@dataclass(frozen=True)
class GrowwHolding:
    scheme_name: str
    category: str
    sub_category: str
    folio_no: str
    units: Decimal
    invested_value: Decimal
    current_value: Decimal
    returns: Decimal
    xirr: Decimal | None = None


@dataclass(frozen=True)
class GrowwHoldingsSnapshot:
    statement_date: date
    holdings: tuple[GrowwHolding, ...]


def parse_groww_xlsx(payload: bytes) -> GrowwHoldingsSnapshot:
    """Parse a Groww holdings export without saving or logging its contents."""
    if not isinstance(payload, bytes) or not payload.startswith(b"PK\x03\x04"):
        raise GrowwImportError("The selected file is not a valid XLSX workbook.")
    if len(payload) > MAX_XLSX_BYTES:
        raise GrowwImportError("The workbook is too large to import (maximum 25 MB).")

    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - deployment packaging guard
        raise GrowwImportError("XLSX import support is not installed on this service.") from exc

    try:
        workbook = load_workbook(BytesIO(payload), read_only=True, data_only=True)
    except Exception as exc:
        raise GrowwImportError("The workbook could not be opened. Upload a complete Groww XLSX export.") from exc

    try:
        if not workbook.worksheets or len(workbook.worksheets) > MAX_WORKSHEETS:
            raise GrowwImportError("The workbook has an unsupported number of sheets.")

        tables: list[tuple[object, int, dict[str, int]]] = []
        statement_dates: set[date] = set()
        for worksheet in workbook.worksheets:
            if (worksheet.max_row and worksheet.max_row > MAX_SCAN_ROWS) or (
                worksheet.max_column and worksheet.max_column > MAX_SCAN_COLUMNS
            ):
                raise GrowwImportError("The workbook has an unsupported sheet size. No sheet data was changed.")
            rows = worksheet.iter_rows(
                min_row=1,
                max_row=min(worksheet.max_row or MAX_SCAN_ROWS, MAX_SCAN_ROWS),
                max_col=min(worksheet.max_column or MAX_SCAN_COLUMNS, MAX_SCAN_COLUMNS),
                values_only=True,
            )
            cached_rows = list(rows)
            statement_dates.update(_find_statement_dates(cached_rows))
            header = _find_table_header(cached_rows)
            if header is not None:
                row_index, columns = header
                tables.append((worksheet, row_index, columns))

        if len(statement_dates) != 1:
            raise GrowwImportError(
                "The workbook must contain one clear 'Holdings As On' date. No sheet data was changed."
            )
        if len(tables) != 1:
            raise GrowwImportError(
                "The workbook must contain one clear Groww holdings table. No sheet data was changed."
            )

        worksheet, header_row, columns = tables[0]
        parsed = _parse_table(worksheet, header_row, columns)
        if not parsed:
            raise GrowwImportError("The Groww holdings table has no fund rows. No sheet data was changed.")
        return GrowwHoldingsSnapshot(statement_date=next(iter(statement_dates)), holdings=tuple(parsed))
    finally:
        workbook.close()


_REQUIRED_COLUMNS = {
    "scheme_name", "category", "sub_category", "folio_no", "units",
    "invested_value", "current_value", "returns",
}


def _find_table_header(rows: Iterable[tuple[object, ...]]) -> tuple[int, dict[str, int]] | None:
    for row_index, row in enumerate(rows):
        columns: dict[str, int] = {}
        for column_index, raw in enumerate(row):
            kind = _header_kind(raw)
            if kind and kind not in columns:
                columns[kind] = column_index
        if _REQUIRED_COLUMNS.issubset(columns):
            return row_index, columns
    return None


def _header_kind(value: object) -> str | None:
    label = re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()
    if label in {"scheme name", "fund name", "mutual fund name"}:
        return "scheme_name"
    if label == "category":
        return "category"
    if label in {"sub category", "subcategory", "sub category name"}:
        return "sub_category"
    if label in {"folio", "folio no", "folio number", "folio no."}:
        return "folio_no"
    if label in {"units", "unit", "quantity"}:
        return "units"
    if label in {"invested value", "invested amount", "amount invested"}:
        return "invested_value"
    if label in {"current value", "current amount", "market value"}:
        return "current_value"
    if label in {"returns", "return", "gain loss", "gain/loss"}:
        return "returns"
    if label in {"xirr", "annualized return"}:
        return "xirr"
    return None


def _find_statement_dates(rows: Iterable[tuple[object, ...]]) -> set[date]:
    found: set[date] = set()
    for row in rows:
        for column_index, value in enumerate(row):
            if isinstance(value, (datetime, date)):
                continue
            text = str(value or "")
            match = re.search(r"holdings\s+as\s+on\s*[:\-]?\s*(.*)$", text, re.IGNORECASE)
            if match:
                parsed = _parse_date_text(match.group(1))
                if parsed:
                    found.add(parsed)
                elif column_index + 1 < len(row):
                    parsed = _parse_date_text(row[column_index + 1])
                    if parsed:
                        found.add(parsed)
    return found


_DATE_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y",
    "%d-%b-%Y", "%d %b %Y", "%d-%B-%Y", "%d %B %Y", "%d-%m-%y", "%d/%m/%y",
)


def _parse_date_text(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    # Permit the timestamp format after the statement label, but only use its date.
    text = re.sub(r"\s+00:00:00(?:\.0+)?$", "", text)
    for date_format in _DATE_FORMATS:
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            continue
    return None


def _parse_table(worksheet: object, header_row: int, columns: dict[str, int]) -> list[GrowwHolding]:
    results: list[GrowwHolding] = []
    rows = worksheet.iter_rows(
        min_row=header_row + 2,
        max_row=min(worksheet.max_row or MAX_SCAN_ROWS, MAX_SCAN_ROWS),
        max_col=min(worksheet.max_column or MAX_SCAN_COLUMNS, MAX_SCAN_COLUMNS),
        values_only=True,
    )
    for row_number, row in enumerate(rows, start=header_row + 2):
        name = _text(_cell(row, columns["scheme_name"]))
        if not name:
            if any(_text(value) for value in row):
                raise GrowwImportError(
                    f"A holdings row near spreadsheet row {row_number} is missing its scheme name. "
                    "No sheet data was changed."
                )
            continue
        if re.search(r"\b(total|grand total|portfolio summary|holdings summary)\b", name, re.IGNORECASE):
            continue

        category = _text(_cell(row, columns["category"]))
        sub_category = _text(_cell(row, columns["sub_category"]))
        folio = _text(_cell(row, columns["folio_no"]))
        if not all((category, sub_category, folio)):
            raise GrowwImportError(
                f"A holdings row near spreadsheet row {row_number} is missing its category, sub-category, or folio. "
                "No sheet data was changed."
            )

        try:
            units = _decimal(_cell(row, columns["units"]), "units", row_number)
            invested = _decimal(_cell(row, columns["invested_value"]), "invested value", row_number)
            current = _decimal(_cell(row, columns["current_value"]), "current value", row_number)
            returns = _decimal(_cell(row, columns["returns"]), "returns", row_number)
            xirr = _xirr(_cell(row, columns["xirr"])) if "xirr" in columns else None
        except ValueError as exc:
            raise GrowwImportError(str(exc)) from exc
        if units < 0 or invested < 0 or current < 0:
            raise GrowwImportError(
                f"A holdings row near spreadsheet row {row_number} contains a negative units or value field. "
                "No sheet data was changed."
            )
        results.append(GrowwHolding(
            scheme_name=name,
            category=category,
            sub_category=sub_category,
            folio_no=folio,
            units=units,
            invested_value=invested,
            current_value=current,
            returns=returns,
            xirr=xirr,
        ))
    return results


def _cell(row: tuple[object, ...], index: int) -> object:
    return row[index] if index < len(row) else None


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _decimal(value: object, label: str, row_number: int) -> Decimal:
    parsed = _decimal_or_none(value)
    if parsed is None:
        raise ValueError(f"The {label} is missing or invalid near spreadsheet row {row_number}. No sheet data was changed.")
    if not parsed.is_finite():
        raise ValueError(f"The {label} is not finite near spreadsheet row {row_number}. No sheet data was changed.")
    return parsed


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            return None
        return Decimal(str(value))
    text = str(value).strip().replace(",", "").replace("\u00a0", " ")
    text = text.replace("₹", "").replace("INR", "").replace("Rs.", "").replace("Rs", "").strip()
    if not text or text in {"-", "—", "–", "NA", "N/A"}:
        return None
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1].strip()
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def _xirr(value: object) -> Decimal | None:
    if value is None or _text(value) in {"", "-", "—", "–", "NA", "N/A"}:
        return None
    percent = isinstance(value, str) and value.strip().endswith("%")
    text = _text(value).removesuffix("%").strip()
    parsed = _decimal_or_none(text)
    if parsed is None:
        raise ValueError("An XIRR value in the Groww file is invalid. No sheet data was changed.")
    if percent or abs(parsed) > 1:
        parsed /= Decimal(100)
    return parsed
