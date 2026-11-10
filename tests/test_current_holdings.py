from datetime import date
from decimal import Decimal

import pytest

from mfhelper.current_holdings import read_current_holdings
from mfhelper.groww_holdings_sheet import HEADERS


class FakeWorksheet:
    def __init__(self, rows):
        self.rows = rows

    def get_all_values(self):
        return self.rows


class FakeSpreadsheet:
    def __init__(self, rows):
        self.worksheet_instance = FakeWorksheet(rows)

    def worksheet(self, name):
        assert name == "Current Holdings"
        return self.worksheet_instance


class FakeClient:
    def __init__(self, spreadsheet):
        self.spreadsheet = spreadsheet

    def open_by_key(self, key):
        assert key == "spreadsheet-id"
        return self.spreadsheet


def _rows():
    return [
        list(HEADERS),
        ["Fund A", "123", "exact_config", "Equity", "Flexi", "1", "1", "100", "150", "50", "0.1", "2026-11-10", "2026-11-11"],
        ["Fund B", "", "unmatched", "Equity", "Mid Cap", "2", "2", "200", "250", "50", "", "2026-11-10", "2026-11-11"],
        ["Fund A", "123", "mfapi_search", "Equity", "Flexi", "3", "2", "200", "350", "150", "0.2", "2026-11-10", "2026-11-11"],
    ]


def test_reads_latest_holdings_and_aggregates_folios_by_amfi_code():
    spreadsheet = FakeSpreadsheet(_rows())
    context = read_current_holdings(
        spreadsheet_id="spreadsheet-id",
        credentials_path=None,
        token_path=None,
        client_factory=lambda _credentials, _token: FakeClient(spreadsheet),
    )

    assert context.statement_date == date(2026, 11, 10)
    assert context.total_current_value == Decimal("750")
    assert context.current_value_by_code == {"123": Decimal("500")}
    assert "₹500" in context.note_for("123")
    assert "66.7%" in context.note_for("123")
    assert "No holding recorded" in context.note_for("999")


@pytest.mark.parametrize(
    "rows",
    [[], [["unexpected header"]], [list(HEADERS), ["Fund", "123", "exact_config", "Equity", "Flexi", "1", "1", "100", "bad", "0", "", "2026-11-10", "now"]]],
)
def test_rejects_invalid_current_holdings_sheet(rows):
    spreadsheet = FakeSpreadsheet(rows)
    with pytest.raises(ValueError):
        read_current_holdings(
            spreadsheet_id="spreadsheet-id",
            credentials_path=None,
            token_path=None,
            client_factory=lambda _credentials, _token: FakeClient(spreadsheet),
        )
