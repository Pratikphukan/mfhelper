from datetime import date, datetime
from decimal import Decimal

import pytest

from mfhelper.groww_holdings_import import GrowwHolding, GrowwHoldingsSnapshot
import mfhelper.groww_holdings_sheet as holdings_sheet
from mfhelper.groww_holdings_sheet import (
    FUND_CODE_MAP_HEADERS,
    HEADERS,
    CurrentHoldingsSheetWriter,
    FundCodeMapSheetReader,
    HoldingsSheetError,
    make_sheet_values,
    match_scheme_code,
    normalize_scheme_name,
    parse_fund_code_map,
    parse_fund_code_map_rows,
)


def test_fund_code_map_requires_unique_exact_normalized_name_match():
    mapping = parse_fund_code_map(
        '[{"name":"JM Flexi-Cap Fund Direct Growth","code":"123456"},'
        '{"name":"Other Fund Direct Growth","code":"456789"}]'
    )

    assert match_scheme_code(
        "jm flexi cap fund DIRECT Growth", mapping,
        search=lambda _name: pytest.fail("private exact match should not call MFAPI"),
    ) == ("123456", "exact_config")
    assert match_scheme_code(
        "JM Flexi Cap Fund Regular Growth", mapping, search=lambda _name: ()
    ) == ("", "unmatched")
    assert normalize_scheme_name(" A&B—C ") == "a b c"


@pytest.mark.parametrize("raw", ["", "{}", "[]", "not json", '[{"name":"Fund","code":"bad"}]'])
def test_invalid_fund_code_maps_are_rejected(raw):
    with pytest.raises(HoldingsSheetError):
        parse_fund_code_map(raw)


def test_unique_mfapi_candidate_can_resolve_multiple_private_map_entries():
    mapping = parse_fund_code_map(
        '[{"name":"Same Fund Direct Growth","code":"123"},'
        '{"name":"Same Fund Direct Growth","code":"456"}]'
    )

    assert match_scheme_code(
        "Same Fund Direct Growth", mapping,
        search=lambda _name: [("789", "Same Fund Direct Plan Growth Option")],
    ) == ("789", "mfapi_search")


def test_mfapi_search_parses_results_and_caches_them(monkeypatch):
    query = "Synthetic MFAPI Cache Test Direct Growth"
    cache_key = normalize_scheme_name(query)
    holdings_sheet._MFAPI_CACHE.pop(cache_key, None)
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return [
                {"schemeCode": 123456, "schemeName": "Synthetic MFAPI Cache Test - Direct Plan - Growth"},
                {"schemeCode": 654321, "schemeName": "Synthetic MFAPI Cache Test - Regular Plan - Growth"},
            ]

    def fake_get(url, *, params, timeout):
        calls.append((url, params, timeout))
        return FakeResponse()

    monkeypatch.setattr(holdings_sheet.requests, "get", fake_get)
    assert match_scheme_code(query, {}) == ("123456", "mfapi_search")
    assert match_scheme_code(query, {}) == ("123456", "mfapi_search")
    assert calls == [(holdings_sheet.MFAPI_SEARCH_URL, {"q": query}, (2, 4))]


def test_mfapi_failure_keeps_holding_row_without_a_code(monkeypatch):
    snapshot = GrowwHoldingsSnapshot(
        statement_date=date(2026, 11, 10),
        holdings=(GrowwHolding(
            scheme_name="Not Listed Fund Direct Growth",
            category="Equity",
            sub_category="Flexi Cap",
            folio_no="000123",
            units=Decimal("1"),
            invested_value=Decimal("100"),
            current_value=Decimal("110"),
            returns=Decimal("10"),
        ),),
    )
    monkeypatch.setattr(holdings_sheet, "_search_mfapi", lambda _name: ())

    values, unmatched = make_sheet_values(snapshot, {})

    assert values[1][1:3] == ["", "unmatched"]
    assert values[1][0] == "Not Listed Fund Direct Growth"
    assert unmatched == 1


def test_mfapi_accepts_only_one_exact_direct_growth_candidate():
    empty_map = {}
    name = "Sample Flexi Cap Fund Direct Growth"

    assert match_scheme_code(
        name,
        empty_map,
        search=lambda _query: [("123456", "Sample Flexi Cap Fund - Direct Plan - Growth Option")],
    ) == ("123456", "mfapi_search")
    assert match_scheme_code(
        name,
        empty_map,
        search=lambda _query: [
            ("123456", "Sample Flexi Cap Fund - Direct Plan - Growth"),
            ("654321", "Sample Flexi Cap Fund - Direct Plan - Growth Option"),
        ],
    ) == ("", "ambiguous")
    assert match_scheme_code(
        name,
        empty_map,
        search=lambda _query: [("987654", "Sample Flexi Cap Fund - Regular Plan - Growth")],
    ) == ("", "unmatched")
    assert match_scheme_code(
        name, empty_map, search=lambda _query: (_ for _ in ()).throw(TimeoutError())
    ) == ("", "unmatched")


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
    assert values[1][1:3] == ["123456", "exact_config"]
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
    values = [list(HEADERS), ["Fund", "123", "exact_config", "Equity", "Flexi", "1", 1, 2, 3, 1, 0.1, "2026-11-10", "2026-11-11"]]
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


def test_parse_fund_code_map_rows_valid():
    rows = [
        list(FUND_CODE_MAP_HEADERS),
        ["JM Flexi Cap Fund Direct Growth", "120492"],
        ["Motilal Oswal Midcap Fund Direct Growth", 127042],
        ["", ""],  # empty row ignored
    ]
    mapping = parse_fund_code_map_rows(rows)
    assert mapping[normalize_scheme_name("JM Flexi Cap Fund Direct Growth")] == ("120492",)
    assert mapping[normalize_scheme_name("Motilal Oswal Midcap Fund Direct Growth")] == ("127042",)


@pytest.mark.parametrize(
    "rows,match",
    [
        ([], "must start with Scheme Name"),
        ([["Wrong Header", "AMFI"]], "must start with Scheme Name"),
        ([list(FUND_CODE_MAP_HEADERS), ["", "120492"]], "invalid row 2"),
        ([list(FUND_CODE_MAP_HEADERS), ["Fund Name", "not-a-code"]], "invalid row 2"),
    ],
)
def test_parse_fund_code_map_rows_malformed(rows, match):
    with pytest.raises(HoldingsSheetError, match=match):
        parse_fund_code_map_rows(rows)


def test_fund_code_map_sheet_reader_success():
    class FakeMapWorksheet:
        def get(self, _range, **_kwargs):
            return [
                list(FUND_CODE_MAP_HEADERS),
                ["Sample Fund Direct Growth", "123456"],
            ]

    class FakeSpreadsheetWithMap:
        def worksheet(self, name):
            assert name == "Fund Code Map"
            return FakeMapWorksheet()

    reader = FundCodeMapSheetReader(
        spreadsheet_id="fake-id",
        service_account_info={},
        client_factory=lambda _info: FakeClient(FakeSpreadsheetWithMap()),
    )
    result = reader.read()
    assert result[normalize_scheme_name("Sample Fund Direct Growth")] == ("123456",)


def test_fund_code_map_sheet_reader_missing_tab():
    import gspread

    class FakeSpreadsheetMissing:
        def worksheet(self, _name):
            raise gspread.WorksheetNotFound("Fund Code Map")

    reader = FundCodeMapSheetReader(
        spreadsheet_id="fake-id",
        service_account_info={},
        client_factory=lambda _info: FakeClient(FakeSpreadsheetMissing()),
    )
    with pytest.raises(HoldingsSheetError, match="Fund Code Map' tab was not found"):
        reader.read()


def test_atomic_replace_clears_full_width_when_old_grid_has_extra_columns():
    class FakeWideWorksheet(FakeWorksheet):
        col_count = 16  # Old sheet has 16 columns, new HEADERS has 13

    worksheet = FakeWideWorksheet(list(HEADERS))
    spreadsheet = FakeSpreadsheet(worksheet)
    writer = CurrentHoldingsSheetWriter(
        spreadsheet_id="fake-id",
        service_account_info={},
        client_factory=lambda _info: FakeClient(spreadsheet),
    )
    writer.replace([list(HEADERS)])

    update = spreadsheet.requests[1]["updateCells"]
    # Verify update range clears all 16 columns
    assert update["range"]["endColumnIndex"] == 16
    assert len(update["rows"][0]["values"]) == 16
