from datetime import date, datetime
from decimal import Decimal

import pytest

from mfhelper.groww_holdings_import import GrowwHolding, GrowwHoldingsSnapshot
from mfhelper.groww_holdings_sheet import (
    HEADERS,
    CurrentHoldingsSheetWriter,
    HoldingsSheetError,
    make_sheet_values,
    match_scheme_code,
    normalize_scheme_name,
    parse_fund_code_map,
)


def test_fund_code_map_requires_unique_exact_normalized_name_match():
    mapping = parse_fund_code_map(
        '[{"name":"JM Flexi-Cap Fund Direct Growth","code":"123456"},'
        '{"name":"Other Fund Direct Growth","code":"456789"}]'
    )

    assert match_scheme_code("jm flexi cap fund DIRECT Growth", mapping) == ("123456", "Matched")
    assert match_scheme_code("JM Flexi Cap Fund Regular Growth", mapping) == ("", "Needs review")
    assert normalize_scheme_name(" A&B—C ") == "a b c"


@pytest.mark.parametrize("raw", ["", "{}", "[]", "not json", '[{"name":"Fund","code":"bad"}]'])
def test_invalid_fund_code_maps_are_rejected(raw):
    with pytest.raises(HoldingsSheetError):
        parse_fund_code_map(raw)


def test_ambiguous_code_map_leaves_code_blank():
    mapping = parse_fund_code_map(
        '[{"name":"Same Fund Direct Growth","code":"123"},'
        '{"name":"Same Fund Direct Growth","code":"456"}]'
    )

    assert match_scheme_code("Same Fund Direct Growth", mapping) == ("", "Needs review")


def test_sheet_values_include_statement_date_timestamp_and_no_unapproved_fields():
    snapshot = GrowwHoldingsSnapshot(
        statement_date=date(2026, 11, 10),
        holdings=(GrowwHolding(
            scheme_name="Sample Direct Growth",
            category="Equity",
            sub_category="Flexi Cap",
            folio_no="000123",
            units=Decimal("2.5"),
            invested_value=Decimal("1000"),
            current_value=Decimal("1200"),
            returns=Decimal("200"),
            xirr=Decimal("0.1"),
        ),),
    )
    mapping = parse_fund_code_map('[{"name":"Sample Direct Growth","code":"123456"}]')

    values, unmatched = make_sheet_values(
        snapshot,
        mapping,
        imported_at=datetime.fromisoformat("2026-11-11T10:30:00+05:30"),
    )

    assert values[0] == list(HEADERS)
    assert values[1][1:3] == ["123456", "Matched"]
    assert values[1][5] == "000123"
    assert values[1][11:] == ["2026-11-10", "2026-11-11 10:30:00"]
    assert unmatched == 0
    assert "AMC" not in HEADERS and "Source" not in HEADERS


class FakeWorksheet:
    id = 42
    row_count = 2
    col_count = 13

    def __init__(self, header):
        self.header = header

    def row_values(self, _row):
        return self.header


class FakeSpreadsheet:
    def __init__(self, worksheet):
        self._worksheet = worksheet
        self.requests = None

    def worksheet(self, _name):
        return self._worksheet

    def batch_update(self, body):
        self.requests = body["requests"]


class FakeClient:
    def __init__(self, spreadsheet):
        self.spreadsheet = spreadsheet

    def open_by_key(self, _key):
        return self.spreadsheet


def test_sheet_replacement_expands_and_clears_old_rows_in_one_batch():
    worksheet = FakeWorksheet(list(HEADERS))
    spreadsheet = FakeSpreadsheet(worksheet)
    writer = CurrentHoldingsSheetWriter(
        spreadsheet_id="fake-id",
        service_account_info={},
        client_factory=lambda _info: FakeClient(spreadsheet),
    )
    values = [list(HEADERS), ["Fund", "123", "Matched", "Equity", "Flexi", "1", 1, 2, 3, 1, 0.1, "2026-11-10", "2026-11-11"]]
    values.extend([[f"Fund {index}"] + [""] * (len(HEADERS) - 1) for index in range(4)])

    writer.replace(values)

    requests = spreadsheet.requests
    assert requests[0]["updateSheetProperties"]["properties"]["gridProperties"]["rowCount"] >= len(values)
    update = requests[1]["updateCells"]
    assert update["range"]["endRowIndex"] >= len(values)
    assert len(update["rows"]) == update["range"]["endRowIndex"]
    assert requests[2]["repeatCell"]


def test_sheet_with_unexpected_existing_header_is_left_unchanged():
    worksheet = FakeWorksheet(["Other data"])
    spreadsheet = FakeSpreadsheet(worksheet)
    writer = CurrentHoldingsSheetWriter(
        spreadsheet_id="fake-id",
        service_account_info={},
        client_factory=lambda _info: FakeClient(spreadsheet),
    )

    with pytest.raises(HoldingsSheetError, match="different layout"):
        writer.replace([list(HEADERS)])

    assert spreadsheet.requests is None
