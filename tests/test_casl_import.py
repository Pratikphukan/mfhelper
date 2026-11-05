from datetime import date

import pytest

from mfhelper.casl_import import CasImportError, _find_statement_date


def test_prefers_portfolio_date_over_generic_nav_and_generation_dates():
    text = """
    Portfolio as on 31-Oct-2026
    NAV as on 28-Oct-2026
    Statement generated as on 02-Nov-2026
    """

    assert _find_statement_date(text) == date(2026, 10, 31)


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
