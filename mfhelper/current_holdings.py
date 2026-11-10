"""Read the latest user holdings tab for daily alert context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import logging
from pathlib import Path

from mfhelper.groww_holdings_sheet import HEADERS, TAB_NAME
from mfhelper.sheets import _load_credentials

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CurrentHoldingsContext:
    statement_date: date
    total_current_value: Decimal
    current_value_by_code: dict[str, Decimal]

    def note_for(self, scheme_code: str) -> str:
        if self.total_current_value <= 0:
            return f"Latest Groww holdings are as of {self.statement_date.isoformat()}; total value was unavailable."
        value = self.current_value_by_code.get(str(scheme_code), Decimal(0))
        share = (value / self.total_current_value) * Decimal(100)
        if value <= 0:
            return f"No holding recorded for this fund in your latest Groww statement (as of {self.statement_date.isoformat()})."
        return (
            f"Your reported holding: ₹{value:,.0f} ({share:.1f}% of reported MF holdings), "
            f"as of {self.statement_date.isoformat()}."
        )


def read_current_holdings(
    *,
    spreadsheet_id: str,
    credentials_path: Path,
    token_path: Path,
    worksheet_name: str = TAB_NAME,
    client_factory=None,
) -> CurrentHoldingsContext | None:
    """Load the latest Groww holdings from Sheets; return None if the tab is absent."""
    try:
        if client_factory is None:
            import gspread

            credentials = _load_credentials(credentials_path, token_path)
            client = gspread.authorize(credentials)
        else:
            client = client_factory(credentials_path, token_path)
        spreadsheet = client.open_by_key(spreadsheet_id)
        try:
            worksheet = spreadsheet.worksheet(worksheet_name)
        except Exception as exc:
            try:
                import gspread
                missing = isinstance(exc, gspread.WorksheetNotFound)
            except ImportError:
                missing = False
            if missing:
                return None
            raise
        rows = worksheet.get_all_values()
    except Exception:
        raise

    if not rows or rows[0] != list(HEADERS):
        raise ValueError("The Current Holdings tab is empty or has an unsupported layout.")

    statement_dates: set[date] = set()
    values_by_code: dict[str, Decimal] = {}
    total = Decimal(0)
    for row in rows[1:]:
        if len(row) < len(HEADERS) or not any(str(value).strip() for value in row):
            continue
        code = str(row[1]).strip()
        status = str(row[2]).strip()
        current = _decimal(row[8])
        total += current
        if status == "Matched" and code:
            values_by_code[code] = values_by_code.get(code, Decimal(0)) + current
        try:
            statement_dates.add(date.fromisoformat(str(row[11]).strip()))
        except ValueError as exc:
            raise ValueError("A statement date in Current Holdings is invalid.") from exc

    if not statement_dates:
        raise ValueError("Current Holdings has no valid statement date.")
    if len(statement_dates) != 1:
        raise ValueError("Current Holdings contains more than one statement date.")
    return CurrentHoldingsContext(
        statement_date=next(iter(statement_dates)),
        total_current_value=total,
        current_value_by_code=values_by_code,
    )


def _decimal(value: object) -> Decimal:
    try:
        result = Decimal(str(value).replace(",", "").replace("₹", "").strip())
    except (InvalidOperation, ValueError):
        raise ValueError("A current value in Current Holdings is invalid.") from None
    if not result.is_finite() or result < 0:
        raise ValueError("A current value in Current Holdings is invalid.")
    return result
