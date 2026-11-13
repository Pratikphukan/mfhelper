from datetime import date, datetime
from decimal import Decimal

import pytest

from mfhelper.groww_holdings_sheet import HEADERS, parse_fund_code_map_rows
from mfhelper.overlap import HoldingItem
from mfhelper.portfolio_overlap import (
    FundPosition,
    PortfolioOverlapInputError,
    PortfolioSnapshot,
    calculate_stock_exposures,
    parse_current_holdings,
    read_portfolio_sheet,
)
from mfhelper.overlap_sheet import OverlapSheetWriter


def _holding_row(name, code, status, folio, current, statement="2026-11-10"):
    return [name, code, status, "Equity", "Flexi Cap", folio, "1", "100", current,
            "0", "", statement, "2026-11-11 10:00:00"]


def test_parse_current_holdings_aggregates_folios_and_resolves_name_from_map():
    code_map = parse_fund_code_map_rows([
        ["Scheme Name", "AMFI Scheme Code"],
        ["Fund A Direct Growth", 123456],
        ["Unmatched Fund Direct Growth", "654321"],
    ])
    snapshot = parse_current_holdings([
        list(HEADERS),
        _holding_row("Fund A Direct Growth", "123456", "exact_config", "folio-1", "1000"),
        _holding_row("Fund A Direct Growth", "123456", "exact_config", "folio-2", "2500"),
        _holding_row("Unmatched Fund Direct Growth", "", "unmatched", "folio-3", "500"),
        _holding_row("Unknown Fund", "", "unmatched", "folio-4", "300"),
    ], code_map)

    assert snapshot.statement_date == date(2026, 11, 10)
    assert snapshot.total_current_value == Decimal("4300")
    assert snapshot.positions_by_code["123456"].current_value == Decimal("3500")
    assert snapshot.positions_by_code["654321"].current_value == Decimal("500")
    assert [(item.name, item.current_value) for item in snapshot.unmapped_positions] == [
        ("Unknown Fund", Decimal("300"))
    ]


def test_conflicting_fund_map_codes_leave_position_unmapped():
    code_map = parse_fund_code_map_rows([
        ["Scheme Name", "AMFI Scheme Code"],
        ["Same Fund Direct Growth", "123456"],
        ["Same Fund Direct Growth", "654321"],
    ])

    snapshot = parse_current_holdings([
        list(HEADERS),
        _holding_row("Same Fund Direct Growth", "", "ambiguous", "folio", "100"),
    ], code_map)

    assert snapshot.positions_by_code == {}
    assert snapshot.unmapped_positions[0].reason == "Fund Code Map has conflicting AMFI codes for this name"


@pytest.mark.parametrize("rows", [
    [],
    [["wrong", "headers"]],
    [list(HEADERS), _holding_row("Fund", "123", "exact_config", "folio", "bad")],
    [list(HEADERS), _holding_row("Fund", "123", "exact_config", "folio", "100", "invalid-date")],
])
def test_invalid_current_holdings_is_rejected(rows):
    with pytest.raises(PortfolioOverlapInputError):
        parse_current_holdings(rows, {})


def test_portfolio_exposure_weights_stock_by_position_value_and_combines_funds():
    positions = {
        "111": FundPosition("111", "Fund A", Decimal("6000")),
        "222": FundPosition("222", "Fund B", Decimal("4000")),
    }
    holdings = {
        "111": [
            HoldingItem("Common Co", 10, "sid-common", "COM", "Equity"),
            HoldingItem("Only A", 50, "sid-a", "A", "Equity"),
            HoldingItem("Bond", 90, "sid-bond", "BOND", "Debt"),
        ],
        "222": [
            HoldingItem("Common Company", 20, "sid-common", "COM", "Equity"),
            HoldingItem("Only B", 50, "sid-b", "B", "Equity"),
        ],
    }

    exposures = calculate_stock_exposures(positions, holdings, Decimal("10000"))

    common = next(item for item in exposures if item.ticker == "COM")
    assert common.estimated_value == Decimal("1400.0")
    assert common.portfolio_pct == Decimal("14.000")
    assert common.fund_count == 2
    assert common.fund_names == ("Fund A", "Fund B")
    assert all(item.ticker != "BOND" for item in exposures)


def test_stock_exposure_is_empty_without_total_value():
    assert calculate_stock_exposures({}, {}, Decimal("0")) == []


def test_read_portfolio_sheet_uses_fund_code_map_and_requested_holdings_tab():
    class FakeWorksheet:
        def __init__(self, rows):
            self.rows = rows

        def get(self, _range, *, value_render_option):
            assert value_render_option == "UNFORMATTED_VALUE"
            return self.rows

        def get_all_values(self):
            return self.rows

    class FakeSpreadsheet:
        tabs = {
            "Fund Code Map": FakeWorksheet([
                ["Scheme Name", "AMFI Scheme Code"],
                ["Fund A Direct Growth", "123456"],
            ]),
            "Current Holdings (Dev)": FakeWorksheet([
                list(HEADERS),
                _holding_row("Fund A Direct Growth", "", "unmatched", "folio", "100"),
            ]),
        }

        def worksheet(self, name):
            return self.tabs[name]

    class FakeClient:
        def open_by_key(self, spreadsheet_id):
            assert spreadsheet_id == "sheet-123"
            return FakeSpreadsheet()

    snapshot, code_map = read_portfolio_sheet(
        spreadsheet_id="sheet-123",
        credentials_path=None,
        token_path=None,
        holdings_tab="Current Holdings (Dev)",
        client_factory=lambda _credentials, _token: FakeClient(),
    )

    assert snapshot.positions_by_code["123456"].current_value == Decimal("100")
    assert code_map == {"fund a direct growth": ("123456",)}


def test_overlap_writer_places_portfolio_exposure_before_pairwise_matrix(monkeypatch):
    class FakeSpreadsheet:
        def batch_update(self, payload):
            self.format_requests = payload["requests"]

    class FakeWorksheet:
        _properties = {"sheetId": 77}
        spreadsheet = FakeSpreadsheet()

        def clear(self):
            self.cleared = True

        def resize(self, *, rows, cols):
            self.size = (rows, cols)

        def update(self, range_name, values, *, value_input_option):
            self.range_name = range_name
            self.values = values
            self.value_input_option = value_input_option

    worksheet = FakeWorksheet()
    writer = OverlapSheetWriter("sheet", "Portfolio Overlap (Dev)", None, None)
    monkeypatch.setattr(writer, "_connect", lambda: worksheet)
    snapshot = parse_current_holdings([
        list(HEADERS),
        _holding_row("Fund A", "123456", "exact_config", "folio", "1000"),
    ], {})
    exposure = calculate_stock_exposures(
        {"123456": FundPosition("123456", "Fund A", Decimal("1000"))},
        {"123456": [HoldingItem("Common Co", 10, "sid", "COM", "Equity")]},
        Decimal("1000"),
    )

    writer.write_overlap_report(
        ["123456"],
        {"123456": "Fund A"},
        {"123456": {"123456": 100.0}},
        [],
        portfolio_snapshot=snapshot,
        portfolio_exposures=exposure,
        fund_data_issues=[],
        statement_age_days=31,
        now=datetime(2026, 12, 11, 11, 0),
    )

    title_row = worksheet.values[0]
    exposure_title_index = next(i for i, row in enumerate(worksheet.values) if row and row[0].startswith("Largest Underlying"))
    matrix_title_index = next(i for i, row in enumerate(worksheet.values) if row and row[0] == "Pairwise Fund Overlap Matrix (%)")
    stock_row = next(row for row in worksheet.values if row and row[0] == "Common Co")
    assert title_row[0] == "Portfolio-Weighted Mutual Fund Overlap"
    assert worksheet.values[1][5] == "STALE (>30 days)"
    assert "provider as-of date is not supplied" in worksheet.values[4][1]
    assert exposure_title_index < matrix_title_index
    assert stock_row[2] == 100
    assert stock_row[3] == 0.1
    assert worksheet.cleared
    requests = worksheet.spreadsheet.format_requests
    wrap_request = next(request["repeatCell"] for request in requests if "repeatCell" in request)
    assert wrap_request["cell"]["userEnteredFormat"]["wrapStrategy"] == "WRAP"
    assert any("autoResizeDimensions" in request for request in requests)


def test_overlap_main_aborts_without_writing_when_all_constituents_fail(monkeypatch):
    from types import SimpleNamespace
    import overlap_main

    snapshot = PortfolioSnapshot(
        statement_date=date(2026, 11, 10),
        total_current_value=Decimal("1000"),
        positions_by_code={"123456": FundPosition("123456", "Fund A", Decimal("1000"))},
        unmapped_positions=(),
    )
    fake_settings = SimpleNamespace(google_sheet=SimpleNamespace(spreadsheet_id="fake-sheet-id"))
    monkeypatch.setattr(overlap_main, "load_settings", lambda _p: fake_settings)
    monkeypatch.setattr(overlap_main, "read_portfolio_sheet", lambda **_kw: (snapshot, {}))
    # Simulate network outage: 0 funds successfully fetched
    monkeypatch.setattr(overlap_main, "_fetch_constituents", lambda _pos, **_kw: ({}, {}, []))

    sheet_writer_called = False

    class FakeWriter:
        def __init__(self, *args, **kwargs):
            nonlocal sheet_writer_called
            sheet_writer_called = True

    monkeypatch.setattr(overlap_main, "OverlapSheetWriter", FakeWriter)

    exit_code = overlap_main.main(["--dev"])
    assert exit_code == 3
    assert not sheet_writer_called
