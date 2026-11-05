from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest

from mfhelper.casl_import import (
    CasImportError,
    _extract_holdings,
    _find_statement_date,
    _header_kind,
    _parse_decimal,
    _table_header,
    parse_cdsl_cas,
    validate_pan,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("abcde1234f", "ABCDE1234F"),
        (" ABCDE1234F ", "ABCDE1234F"),
    ],
)
def test_validate_pan_accepts_valid_pan_and_normalizes_case(value, expected):
    assert validate_pan(value) == expected


@pytest.mark.parametrize("value", ["", "ABCDE1234", "ABCDE12345F", "ABCDEF1234G", "ABCDE 1234F"])
def test_validate_pan_rejects_invalid_formats(value):
    with pytest.raises(CasImportError):
        validate_pan(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("₹1,23,456.78", Decimal("123456.78")),
        ("Rs. 1,234.50", Decimal("1234.50")),
        ("Rs 1,234", Decimal("1234")),
        ("INR 4,321.00", Decimal("4321.00")),
        ("(1,234.50)", Decimal("-1234.50")),
        ("-₹12.5", Decimal("-12.5")),
    ],
)
def test_parse_decimal_handles_currencies_commas_and_negative_values(value, expected):
    assert _parse_decimal(value) == expected


@pytest.mark.parametrize("value", ["", "-", "N/A", "not a number", "NaN", "Infinity"])
def test_parse_decimal_returns_none_for_missing_or_non_finite_values(value):
    assert _parse_decimal(value) is None


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Scheme Name", "scheme_name"),
        ("Closing Balance (Units)", "closing_units"),
        ("Opening Balance (Units)", "opening_units"),
        ("Units", "units"),
        ("Valuation (₹)", "statement_value"),
        ("AMFI Scheme Code", "scheme_code"),
        ("ISIN", "isin"),
        ("Transaction Amount", None),
    ],
)
def test_header_kind_maps_cas_columns(header, expected):
    assert _header_kind(header) == expected


def test_table_header_combines_wrapped_cdsl_column_labels():
    table = [
        ["Scheme", "ISIN", "", "Closing Balance", "Valuation"],
        ["Name", "", "", "(Units)", "(₹)"],
        ["Sample Fund", "INF200K01RP8", "", "12.5", "1000.00"],
    ]

    assert _table_header(table) == (
        1,
        {"scheme_name": 0, "isin": 1, "units": 3, "statement_value": 4},
    )


def test_table_header_rejects_transaction_amount_instead_of_valuation():
    table = [["Scheme Name", "Units", "Transaction Amount"], ["Fund", "2", "100"]]

    assert _table_header(table) is None


def test_table_header_selects_closing_balance_when_opening_and_closing_exist():
    table = [
        ["Scheme Name", "Opening Balance (Units)", "Closing Balance (Units)", "Valuation"],
        ["Sample Fund", "1", "2", "250.00"],
    ]

    header = _table_header(table)

    assert header is not None
    assert header[1]["units"] == 2
    holdings = _extract_holdings([table])
    assert holdings[0].units == Decimal("2")


def test_rejects_malformed_row_instead_of_saving_partial_holdings():
    table = [
        ["Scheme Name", "Closing Balance (Units)", "Valuation"],
        ["Complete Fund", "2", "250.00"],
        ["Incomplete Fund", "1", ""],
    ]

    with pytest.raises(CasImportError, match="incomplete row"):
        _extract_holdings([table])


def test_prefers_portfolio_date_over_generic_nav_and_generation_dates():
    text = """
    Portfolio as on 31-Oct-2026
    NAV as on 28-Oct-2026
    Statement generated as on 02-Nov-2026
    """

    assert _find_statement_date(text) == date(2026, 10, 31)


def test_uses_end_of_cas_reporting_period_as_holdings_date():
    text = """
    CONSOLIDATED ACCOUNT STATEMENT FOR THE PERIOD FROM 01-09-2026 TO 30-09-2026
    Statement for the period from 01-Sep-2026 to 30-Sep-2026
    NAV as on 28-Sep-2026
    Statement generated as on 02-Oct-2026
    """

    assert _find_statement_date(text) == date(2026, 9, 30)


def test_recognizes_cdsl_labeled_mutual_fund_as_of_date():
    assert _find_statement_date("MUTUAL FUND UNITS HELD AS ON 30-09-2026") == date(2026, 9, 30)


def test_extracts_units_and_valuation_from_cdsl_holdings_table():
    table = [
        [
            "Scheme Name", "ISIN", "Folio No.", "ARN Code",
            "Closing Balance (Units)", "NAV (₹)",
            "Cumulative Amount Invested (In ₹)", "Valuation (₹)",
        ],
        [
            "Sample Mutual Fund Direct Growth", "INF200K01RP8", "folio-redacted", "DIRECT",
            "6872.842", "99.50", "100000.00", "684856.80",
        ],
    ]

    holdings = _extract_holdings([table])

    assert len(holdings) == 1
    assert holdings[0].scheme_name == "Sample Mutual Fund Direct Growth"
    assert holdings[0].isin == "INF200K01RP8"
    assert str(holdings[0].units) == "6872.842"
    assert str(holdings[0].statement_value) == "684856.80"


def test_uses_statement_date_before_generic_as_of_dates():
    text = "Statement Date: 02-Nov-2026\nNAV as on 31-Oct-2026"

    assert _find_statement_date(text) == date(2026, 11, 2)


def test_generic_as_of_fallback_prefers_most_frequent_date():
    text = "NAV as on 31-Oct-2026\nNAV as on 31-Oct-2026\nNAV as of 28-Oct-2026"

    assert _find_statement_date(text) == date(2026, 10, 31)


def test_conflicting_highest_priority_labeled_dates_are_rejected():
    text = "Portfolio as on 31-Oct-2026\nPortfolio as on 30-Oct-2026"

    with pytest.raises(CasImportError, match="conflicting labeled statement dates"):
        _find_statement_date(text)


def _make_encrypted_cdsl_pdf():
    pytest.importorskip("pypdf")
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): writer._add_object(font)}
            )
        }
    )

    content = b"""\
0.5 w
50 660 m 550 660 l S
50 630 m 550 630 l S
50 600 m 550 600 l S
50 600 m 50 660 l S
300 600 m 300 660 l S
425 600 m 425 660 l S
550 600 m 550 660 l S
BT /F1 10 Tf 50 750 Td (Central Depository Services CDSL) Tj ET
BT /F1 10 Tf 50 730 Td (Statement for the period from 01-Sep-2026 to 30-Sep-2026) Tj ET
BT /F1 8 Tf 55 643 Td (Scheme Name) Tj ET
BT /F1 8 Tf 305 643 Td (Closing Balance) Tj ET
BT /F1 8 Tf 305 633 Td ((Units)) Tj ET
BT /F1 8 Tf 430 643 Td (Valuation) Tj ET
BT /F1 8 Tf 55 608 Td (Synthetic Direct Growth) Tj ET
BT /F1 8 Tf 330 608 Td (12.5) Tj ET
BT /F1 8 Tf 455 608 Td (1234.50) Tj ET
"""
    stream = DecodedStreamObject()
    stream.set_data(content)
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.encrypt("ABCDE1234F")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_decrypts_and_extracts_synthetic_encrypted_cdsl_pdf():
    pytest.importorskip("pdfplumber")
    pdf_bytes = _make_encrypted_cdsl_pdf()

    parsed = parse_cdsl_cas(pdf_bytes, "abcde1234f")

    assert parsed.statement_date == date(2026, 9, 30)
    assert len(parsed.holdings) == 1
    assert parsed.holdings[0].scheme_name == "Synthetic Direct Growth"
    assert parsed.holdings[0].units == Decimal("12.5")
    assert parsed.holdings[0].statement_value == Decimal("1234.50")


def test_encrypted_pdf_rejects_incorrect_pan():
    pdf_bytes = _make_encrypted_cdsl_pdf()

    with pytest.raises(CasImportError, match="PAN did not unlock"):
        parse_cdsl_cas(pdf_bytes, "ZZZZZ9999Z")
