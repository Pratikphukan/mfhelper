"""Password-protected CDSL CAS extraction.

The parser deliberately fails closed: a statement is accepted only when it has
an identifiable statement date and a table with fund, unit, and market-value
columns. It never guesses from transaction amounts or partial rows.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
import re
from typing import Iterable


class CasImportError(ValueError):
    """Safe, user-facing import error that does not contain statement data."""


@dataclass(frozen=True)
class Holding:
    scheme_name: str
    units: Decimal
    statement_value: Decimal
    isin: str | None = None
    scheme_code: str | None = None


@dataclass(frozen=True)
class ParsedCas:
    statement_date: date
    holdings: tuple[Holding, ...]


_PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_DATE_TOKEN = (
    r"(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|"
    r"\d{1,2}[-/ .][A-Za-z]{3,9}[-/ .]\d{2,4}|"
    r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4})"
)
_EXPLICIT_DATE_PATTERNS = (
    (
        4,
        re.compile(
            rf"\b(?:portfolio(?:\s+(?:value|valuation))?|holdings?)"
            rf"\s+as\s+(?:on|of)\s*[:\-]?\s*({_DATE_TOKEN})",
            re.IGNORECASE,
        ),
    ),
    (
        3,
        re.compile(
            rf"\b(?:statement\s*(?:date|as\s+on|as\s+of)|date\s+of\s+statement)"
            rf"\s*[:\-]?\s*({_DATE_TOKEN})",
            re.IGNORECASE,
        ),
    ),
    (
        2,
        re.compile(
            rf"\bvaluation\s+as\s+(?:on|of)\s*[:\-]?\s*({_DATE_TOKEN})",
            re.IGNORECASE,
        ),
    ),
)
_GENERIC_AS_OF_DATE_RE = re.compile(
    rf"\b(?:as\s+on|as\s+of)\s*[:\-]?\s*({_DATE_TOKEN})",
    re.IGNORECASE,
)
_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{10}$", re.IGNORECASE)


def validate_pan(value: str) -> str:
    pan = value.strip().upper()
    if not _PAN_RE.fullmatch(pan):
        raise CasImportError("Enter the first or sole holder's valid PAN as the CDSL PDF password.")
    return pan


def parse_cdsl_cas(pdf_bytes: bytes, pan: str) -> ParsedCas:
    """Decrypt and extract holdings, without writing or logging PDF data."""
    if not pdf_bytes.startswith(b"%PDF-"):
        raise CasImportError("The selected file is not a PDF.")
    if len(pdf_bytes) > 25 * 1024 * 1024:
        raise CasImportError("The PDF is too large to import (maximum 25 MB).")

    secret = validate_pan(pan)
    try:
        import pdfplumber
        from pypdf import PdfReader
    except ImportError as exc:
        raise CasImportError("The PDF import dependencies are not installed in this Codespace.") from exc

    stream = BytesIO(pdf_bytes)
    try:
        reader = PdfReader(stream, strict=False)
        if reader.is_encrypted:
            try:
                unlocked = reader.decrypt(secret)
            except Exception as exc:
                raise CasImportError("The PAN did not unlock this PDF.") from exc
            if not unlocked:
                raise CasImportError("The PAN did not unlock this PDF.")
        if not reader.pages:
            raise CasImportError("The PDF has no readable pages.")
        if len(reader.pages) > 200:
            raise CasImportError("The PDF has too many pages to import safely.")
    except CasImportError:
        raise
    except Exception as exc:
        raise CasImportError("The PDF could not be opened. Check that it is a complete CDSL CAS file.") from exc
    finally:
        stream.close()

    try:
        with pdfplumber.open(BytesIO(pdf_bytes), password=secret) as pdf:
            page_texts = [page.extract_text(layout=False) or "" for page in pdf.pages]
            tables = [table for page in pdf.pages for table in page.extract_tables()]
    except Exception as exc:
        # Do not expose the third-party parser's exception: it can include file
        # offsets and PDF internals that are unnecessary to the user.
        raise CasImportError("The PDF opened, but its text or tables could not be read.") from exc

    full_text = "\n".join(page_texts)
    upper_text = full_text.upper()
    if "CDSL" not in upper_text and "CENTRAL DEPOSITORY SERVICES" not in upper_text:
        raise CasImportError("This does not appear to be a CDSL CAS PDF.")

    statement_date = _find_statement_date(full_text)
    holdings = _extract_holdings(tables)
    if not holdings:
        raise CasImportError(
            "The PDF was unlocked, but its holdings table layout is not recognized. "
            "No holdings were saved."
        )
    return ParsedCas(statement_date=statement_date, holdings=tuple(holdings))


def _find_statement_date(text: str) -> date:
    explicit: list[tuple[int, date]] = []
    for priority, pattern in _EXPLICIT_DATE_PATTERNS:
        for match in pattern.finditer(text):
            try:
                explicit.append((priority, _parse_date(match.group(1))))
            except ValueError:
                continue

    if explicit:
        highest_priority = max(priority for priority, _ in explicit)
        selected = [
            parsed_date
            for priority, parsed_date in explicit
            if priority == highest_priority
        ]
        unique_dates = set(selected)
        if len(unique_dates) != 1:
            raise CasImportError(
                "The PDF contains conflicting labeled statement dates. No holdings were saved."
            )
        return selected[0]

    # Some layouts expose only generic "as on/as of" labels. Prefer the date
    # repeated most often (typically the portfolio as-of date); break ties by
    # the first occurrence in document order. These generic matches are only
    # considered when there is no labeled statement/portfolio date.
    generic: list[tuple[int, date]] = []
    for match in _GENERIC_AS_OF_DATE_RE.finditer(text):
        try:
            generic.append((match.start(), _parse_date(match.group(1))))
        except ValueError:
            continue
    if not generic:
        raise CasImportError(
            "The statement date was not recognized. No holdings were saved."
        )
    frequencies = Counter(parsed_date for _, parsed_date in generic)
    most_common = max(frequencies.values())
    frequent_dates = {
        parsed_date
        for parsed_date, count in frequencies.items()
        if count == most_common
    }
    return next(parsed_date for _, parsed_date in generic if parsed_date in frequent_dates)


def _parse_date(value: str) -> date:
    cleaned = re.sub(r"\s+", " ", value.strip())
    for fmt in (
        "%Y-%m-%d", "%Y/%m/%d", "%d-%b-%Y", "%d %b %Y",
        "%d-%B-%Y", "%d %B %Y", "%d/%m/%Y", "%d-%m-%Y",
        "%d/%m/%y", "%d-%m-%y",
    ):
        try:
            return datetime.strptime(cleaned.title(), fmt).date()
        except ValueError:
            continue
    raise ValueError("unsupported date")


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _header_kind(value: str) -> str | None:
    header = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    if not header:
        return None
    if "isin" in header:
        return "isin"
    if "scheme code" in header or "amfi code" in header:
        return "scheme_code"
    if any(word in header for word in ("scheme", "fund name", "mutual fund")):
        return "scheme_name"
    if any(word in header for word in ("unit", "quantity")):
        return "units"
    if any(phrase in header for phrase in (
        "current value", "market value", "closing value", "valuation value",
        "value as on", "value as of", "portfolio value",
    )):
        return "statement_value"
    return None


def _table_header(table: list[list[object]]) -> tuple[int, dict[str, int]] | None:
    # CDSL headings can wrap across adjacent rows. Test a small header window,
    # but require a current/market-value label to avoid transaction amount tables.
    for header_row in range(min(4, len(table))):
        combined = [""] * max((len(row or []) for row in table[: header_row + 1]), default=0)
        for row in table[: header_row + 1]:
            for index, cell in enumerate(row or []):
                text = _norm(cell)
                if text:
                    combined[index] = f"{combined[index]} {text}".strip()
        kinds: dict[str, int] = {}
        for index, cell in enumerate(combined):
            kind = _header_kind(cell)
            if kind and kind not in kinds:
                kinds[kind] = index
        if {"scheme_name", "units", "statement_value"}.issubset(kinds):
            return header_row, kinds
    return None


def _parse_decimal(value: str) -> Decimal | None:
    cleaned = value.strip().replace(",", "")
    cleaned = cleaned.replace("₹", "").replace("Rs.", "").replace("Rs", "")
    cleaned = cleaned.replace("INR", "").replace("\u00a0", "").strip()
    if not cleaned or cleaned in {"-", "—", "–", "NA", "N/A"}:
        return None
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1].strip()
    try:
        number = Decimal(cleaned)
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    return number


def _extract_holdings(tables: Iterable[list[list[object]]]) -> list[Holding]:
    grouped: dict[str, dict[str, object]] = {}
    recognized_table = False
    for table in tables:
        if not table:
            continue
        header_info = _table_header(table)
        if not header_info:
            continue
        recognized_table = True
        header_row, columns = header_info
        for row in table[header_row + 1 :]:
            cells = [_norm(cell) for cell in row or []]
            width = max(columns.values())
            if len(cells) <= width:
                continue
            name = cells[columns["scheme_name"]]
            units = _parse_decimal(cells[columns["units"]])
            value = _parse_decimal(cells[columns["statement_value"]])
            if not name or units is None or value is None:
                continue
            if re.search(r"\b(total|grand total|sub total)\b", name, re.IGNORECASE):
                continue
            if units < 0 or value < 0:
                continue

            isin = None
            if "isin" in columns and len(cells) > columns["isin"]:
                candidate = re.sub(r"\s+", "", cells[columns["isin"]]).upper()
                if _ISIN_RE.fullmatch(candidate):
                    isin = candidate
            scheme_code = None
            if "scheme_code" in columns and len(cells) > columns["scheme_code"]:
                candidate = re.sub(r"\s+", "", cells[columns["scheme_code"]])
                if candidate.isdigit():
                    scheme_code = candidate

            identity = isin or scheme_code or re.sub(r"\W+", " ", name.lower()).strip()
            if not identity:
                continue
            current = grouped.get(identity)
            if current:
                current["units"] = current["units"] + units
                current["value"] = current["value"] + value
            else:
                grouped[identity] = {
                    "scheme_name": name,
                    "units": units,
                    "value": value,
                    "isin": isin,
                    "scheme_code": scheme_code,
                }

    if not recognized_table or not grouped:
        return []
    result = [
        Holding(
            scheme_name=str(item["scheme_name"]),
            units=item["units"],  # type: ignore[arg-type]
            statement_value=item["value"],  # type: ignore[arg-type]
            isin=item["isin"],  # type: ignore[arg-type]
            scheme_code=item["scheme_code"],  # type: ignore[arg-type]
        )
        for item in grouped.values()
    ]
    result.sort(key=lambda holding: (holding.scheme_name.casefold(), holding.isin or ""))
    return result
