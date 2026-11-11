from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest

openpyxl = pytest.importorskip("openpyxl")

from mfhelper.groww_holdings_import import GrowwImportError, parse_groww_xlsx


def _workbook_bytes(*, include_summary=True, statement_date="2026-11-10", bad_row=False):
    workbook = openpyxl.Workbook()
    details = workbook.active
    details.title = "Personal Details"
    details.append(["Investor", "Private User"])
    details.append(["PAN", "ABCDE1234F"])

    sheet = workbook.create_sheet("Holdings")
    sheet.append([f"HOLDINGS AS ON {statement_date}"])
    if include_summary:
        sheet.append(["Total holdings value", 12345])
    sheet.append([
        "Scheme Name", "Category", "Sub-category", "Folio No.", "Units",
        "Invested Value", "Current Value", "Returns", "XIRR", "AMC", "Source",
    ])
    sheet.append([
        "Sample Flexi Cap Direct Growth", "Equity", "Flexi Cap", "001234567890",
        12.5, 10000, 11250.5, 1250.5, "6.5%", "Ignored AMC", "Ignored Source",
    ])
    sheet.append([
        "Sample Midcap Direct Growth", "Equity", "Mid Cap", "001234567891",
        20, 15000, 14800, -200, "-1.25%", "Ignored AMC", "Ignored Source",
    ])
    if bad_row:
        sheet.append([
            "Incomplete Small Cap", "Equity", "Small Cap", "", 2, 100, 120, 20, "", "", "",
        ])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_parses_groww_holdings_and_ignores_personal_details_and_summary():
    snapshot = parse_groww_xlsx(_workbook_bytes())

    assert snapshot.statement_date == date(2026, 11, 10)
    assert len(snapshot.holdings) == 2
    first, second = snapshot.holdings
    assert first.scheme_name == "Sample Flexi Cap Direct Growth"
    assert first.folio_no == "001234567890"
    assert first.units == Decimal("12.5")
    assert first.current_value == Decimal("11250.5")
    assert first.returns == Decimal("1250.5")
    assert first.xirr == Decimal("0.065")
    assert second.returns == Decimal("-200")
    assert second.xirr == Decimal("-0.0125")
    serialized = repr(snapshot)
    assert "ABCDE1234F" not in serialized
    assert "Ignored AMC" not in serialized
    assert "Ignored Source" not in serialized


def test_rejects_unrecognized_workbook_without_groww_holdings_table():
    workbook = openpyxl.Workbook()
    workbook.active.append(["Not a Groww export"])
    output = BytesIO()
    workbook.save(output)

    with pytest.raises(GrowwImportError, match="Holdings As On|holdings table"):
        parse_groww_xlsx(output.getvalue())


def test_rejects_conflicting_statement_dates():
    payload = _workbook_bytes()
    workbook = openpyxl.load_workbook(BytesIO(payload))
    workbook["Personal Details"].append(["HOLDINGS AS ON 2026-10-10"])
    output = BytesIO()
    workbook.save(output)

    with pytest.raises(GrowwImportError, match="one clear 'Holdings As On' date"):
        parse_groww_xlsx(output.getvalue())


def test_rejects_incomplete_holding_row():
    with pytest.raises(GrowwImportError, match="missing its category, sub-category, or folio"):
        parse_groww_xlsx(_workbook_bytes(bad_row=True))


@pytest.mark.parametrize("payload", [b"", b"not xlsx", b"%PDF-1.7"])
def test_rejects_non_xlsx_input(payload):
    with pytest.raises(GrowwImportError, match="not a valid XLSX"):
        parse_groww_xlsx(payload)


def test_finds_statement_date_in_adjacent_cell():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Holdings"
    # Label in column A, date in column B
    sheet.append(["HOLDINGS AS ON", "2026-11-10"])
    sheet.append([
        "Scheme Name", "Category", "Sub-category", "Folio No.", "Units",
        "Invested Value", "Current Value", "Returns", "XIRR",
    ])
    sheet.append([
        "Sample Flexi Cap Direct Growth", "Equity", "Flexi Cap", "001234567890",
        12.5, 10000, 11250.5, 1250.5, "6.5%",
    ])
    output = BytesIO()
    workbook.save(output)

    snapshot = parse_groww_xlsx(output.getvalue())
    assert snapshot.statement_date == date(2026, 11, 10)


def test_rejects_oversized_worksheet_dimensions():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Holdings"
    sheet.append(["HOLDINGS AS ON 2026-11-10"])

    from unittest.mock import patch
    from openpyxl.worksheet._read_only import ReadOnlyWorksheet
    with patch.object(ReadOnlyWorksheet, "max_row", 5001):
        output = BytesIO()
        workbook.save(output)
        with pytest.raises(GrowwImportError, match="unsupported sheet size"):
            parse_groww_xlsx(output.getvalue())
