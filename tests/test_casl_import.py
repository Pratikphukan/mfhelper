from datetime import date

import pytest

from mfhelper.casl_import import CasImportError, _extract_holdings, _find_statement_date


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
