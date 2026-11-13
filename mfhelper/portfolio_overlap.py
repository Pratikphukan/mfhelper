"""Portfolio-weighted calculations for the on-demand overlap report."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import math
from pathlib import Path
from typing import Iterable

from mfhelper.groww_holdings_sheet import (
    FUND_CODE_MAP_TAB_NAME,
    HEADERS,
    HoldingsSheetError,
    normalize_scheme_name,
    parse_fund_code_map_rows,
)
from mfhelper.overlap import HoldingItem
from mfhelper.sheets import _load_credentials


class PortfolioOverlapInputError(ValueError):
    """Required portfolio sheet data is missing or malformed."""


@dataclass(frozen=True)
class FundPosition:
    code: str
    name: str
    current_value: Decimal


@dataclass(frozen=True)
class UnmappedPosition:
    name: str
    current_value: Decimal
    reason: str


@dataclass(frozen=True)
class PortfolioSnapshot:
    statement_date: date
    total_current_value: Decimal
    positions_by_code: dict[str, FundPosition]
    unmapped_positions: tuple[UnmappedPosition, ...]


@dataclass(frozen=True)
class StockExposure:
    company_name: str
    ticker: str
    estimated_value: Decimal
    portfolio_pct: Decimal
    fund_count: int
    fund_names: tuple[str, ...]


@dataclass(frozen=True)
class FundDataIssue:
    code: str
    name: str
    current_value: Decimal
    reason: str


def read_portfolio_sheet(
    *,
    spreadsheet_id: str,
    credentials_path: Path,
    token_path: Path,
    holdings_tab: str = "Current Holdings",
    client_factory=None,
) -> tuple[PortfolioSnapshot, dict[str, tuple[str, ...]]]:
    """Read both required private-sheet tabs before any report write."""
    try:
        if client_factory is None:
            import gspread

            credentials = _load_credentials(credentials_path, token_path)
            client = gspread.authorize(credentials)
        else:
            client = client_factory(credentials_path, token_path)
        spreadsheet = client.open_by_key(spreadsheet_id)
        map_sheet = spreadsheet.worksheet(FUND_CODE_MAP_TAB_NAME)
        holdings_sheet = spreadsheet.worksheet(holdings_tab)
        code_map_rows = map_sheet.get("A:B", value_render_option="UNFORMATTED_VALUE")
        code_map = parse_fund_code_map_rows(code_map_rows)
        snapshot = parse_current_holdings(holdings_sheet.get_all_values(), code_map)
        return snapshot, code_map
    except HoldingsSheetError as exc:
        raise PortfolioOverlapInputError(
            "The Fund Code Map could not be validated. "
            "The previous Portfolio Overlap report was preserved."
        ) from exc
    except PortfolioOverlapInputError:
        raise
    except Exception as exc:
        raise PortfolioOverlapInputError(
            "Google Sheets could not read Fund Code Map and Current Holdings. "
            "The previous Portfolio Overlap report was preserved."
        ) from exc


def parse_current_holdings(
    rows: Iterable[Iterable[object]],
    fund_code_map: dict[str, tuple[str, ...]],
) -> PortfolioSnapshot:
    """Validate a Current Holdings grid and combine folios by AMFI code."""
    values = [list(row) for row in rows]
    if not values or values[0] != list(HEADERS):
        raise PortfolioOverlapInputError(
            "The Current Holdings tab is empty or has an unsupported layout."
        )

    statement_dates: set[date] = set()
    positions: dict[str, FundPosition] = {}
    unmapped: dict[str, UnmappedPosition] = {}
    total = Decimal(0)

    for row_number, raw_row in enumerate(values[1:], start=2):
        if not any(str(value).strip() for value in raw_row):
            continue
        row = list(raw_row) + [""] * max(0, len(HEADERS) - len(raw_row))
        name = str(row[0]).strip()
        raw_code = str(row[1]).strip()
        match_status = str(row[2]).strip()
        current_value = _decimal(row[8], row_number)
        total += current_value

        try:
            statement_dates.add(date.fromisoformat(str(row[11]).strip()))
        except ValueError as exc:
            raise PortfolioOverlapInputError(
                f"The statement date in Current Holdings row {row_number} is invalid."
            ) from exc

        code = ""
        reason = "No unique AMFI code mapping"
        if raw_code.isdigit() and len(raw_code) <= 12 and match_status in {"exact_config", "mfapi_search"}:
            code = raw_code
        else:
            mapped_codes = fund_code_map.get(normalize_scheme_name(name), ())
            if len(mapped_codes) == 1:
                code = mapped_codes[0]
            elif len(mapped_codes) > 1:
                reason = "Fund Code Map has conflicting AMFI codes for this name"

        if code:
            prior = positions.get(code)
            positions[code] = FundPosition(
                code=code,
                name=prior.name if prior else name,
                current_value=(prior.current_value if prior else Decimal(0)) + current_value,
            )
        else:
            key = normalize_scheme_name(name) or f"row {row_number}"
            prior = unmapped.get(key)
            unmapped[key] = UnmappedPosition(
                name=prior.name if prior else (name or f"Unknown fund (row {row_number})"),
                current_value=(prior.current_value if prior else Decimal(0)) + current_value,
                reason=prior.reason if prior else reason,
            )

    if not statement_dates:
        raise PortfolioOverlapInputError("Current Holdings has no valid statement date.")
    if len(statement_dates) != 1:
        raise PortfolioOverlapInputError("Current Holdings contains more than one statement date.")

    return PortfolioSnapshot(
        statement_date=next(iter(statement_dates)),
        total_current_value=total,
        positions_by_code=positions,
        unmapped_positions=tuple(sorted(unmapped.values(), key=lambda item: item.name.casefold())),
    )


def calculate_stock_exposures(
    positions_by_code: dict[str, FundPosition],
    holdings_by_code: dict[str, list[HoldingItem]],
    total_current_value: Decimal,
    *,
    limit: int = 30,
) -> list[StockExposure]:
    """Weight equity holdings by each fund's share of the reported portfolio."""
    if total_current_value <= 0:
        return []

    totals: dict[str, dict[str, object]] = {}
    for code, position in positions_by_code.items():
        if position.current_value <= 0:
            continue
        for holding in holdings_by_code.get(code, []):
            if holding.instrument_type.strip().casefold() not in {"equity", "stock"}:
                continue
            if not math.isfinite(holding.allocation_pct) or holding.allocation_pct <= 0:
                continue
            identity = holding.sid or normalize_scheme_name(holding.company_name)
            if not identity:
                continue
            item = totals.setdefault(identity, {
                "name": holding.company_name,
                "ticker": holding.ticker or "",
                "value": Decimal(0),
                "funds": set(),
            })
            item["value"] = item["value"] + (
                position.current_value * Decimal(str(holding.allocation_pct)) / Decimal(100)
            )
            item["funds"].add(position.name)
            if not item["ticker"] and holding.ticker:
                item["ticker"] = holding.ticker

    exposures = [
        StockExposure(
            company_name=str(item["name"]),
            ticker=str(item["ticker"]),
            estimated_value=item["value"],
            portfolio_pct=item["value"] / total_current_value * Decimal(100),
            fund_count=len(item["funds"]),
            fund_names=tuple(sorted(item["funds"], key=str.casefold)),
        )
        for item in totals.values()
    ]
    exposures.sort(key=lambda item: (-item.estimated_value, item.company_name.casefold()))
    return exposures[:max(0, limit)]


def _decimal(value: object, row_number: int) -> Decimal:
    text = str(value or "").replace(",", "").replace("₹", "").strip()
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise PortfolioOverlapInputError(
            f"The current value in Current Holdings row {row_number} is invalid."
        ) from exc
    if not parsed.is_finite() or parsed < 0:
        raise PortfolioOverlapInputError(
            f"The current value in Current Holdings row {row_number} is invalid."
        )
    return parsed
