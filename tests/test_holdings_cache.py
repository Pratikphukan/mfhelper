from datetime import date, datetime
from decimal import Decimal

from mfhelper.casl_import import Holding, ParsedCas
from mfhelper.holdings_cache import _holdings_equal, snapshot_payload


def test_snapshot_payload_keeps_normalized_holding_fields_without_folio_or_pan():
    parsed = ParsedCas(
        statement_date=date(2026, 9, 30),
        holdings=(
            Holding(
                scheme_name="Sample Fund Direct Growth",
                units=Decimal("12.3400"),
                statement_value=Decimal("1234.50"),
                isin="INF200K01RP8",
                scheme_code="123456",
            ),
        ),
    )

    payload = snapshot_payload(parsed)

    assert payload["schema_version"] == 1
    assert payload["source"] == "cdsl_cas"
    assert payload["statement_date"] == "2026-09-30"
    imported_at = datetime.fromisoformat(payload["imported_at"])
    assert imported_at.utcoffset().total_seconds() == 5.5 * 60 * 60
    assert payload["holdings"] == [
        {
            "isin": "INF200K01RP8",
            "scheme_code": "123456",
            "scheme_name": "Sample Fund Direct Growth",
            "units": "12.34",
            "statement_value_inr": "1234.5",
        }
    ]
    assert "pan" not in str(payload).lower()
    assert "folio" not in str(payload).lower()


def test_holdings_equal_ignores_order_whitespace_case_and_import_metadata():
    first = {
        "statement_date": "2026-09-30",
        "imported_at": "first import",
        "holdings": [
            {
                "isin": "INF200K01RP8",
                "scheme_name": "Sample   Fund",
                "units": "2.5",
                "statement_value_inr": "200",
            },
            {
                "scheme_code": "123456",
                "scheme_name": "Another Fund",
                "units": "1",
                "statement_value_inr": "100",
            },
        ],
    }
    second = {
        "statement_date": "2026-09-30",
        "imported_at": "later import",
        "holdings": [
            {
                "scheme_code": "123456",
                "scheme_name": "Another Fund",
                "units": "1",
                "statement_value_inr": "100",
            },
            {
                "isin": "INF200K01RP8",
                "scheme_name": " sample fund ",
                "units": "2.5",
                "statement_value_inr": "200",
            },
        ],
    }

    assert _holdings_equal(first, second)


def test_holdings_equal_detects_changed_units_or_statement_value():
    original = {
        "holdings": [
            {
                "isin": "INF200K01RP8",
                "scheme_name": "Sample Fund",
                "units": "2.5",
                "statement_value_inr": "200",
            }
        ]
    }
    changed_units = {
        "holdings": [
            {
                "isin": "INF200K01RP8",
                "scheme_name": "Sample Fund",
                "units": "3",
                "statement_value_inr": "200",
            }
        ]
    }
    changed_value = {
        "holdings": [
            {
                "isin": "INF200K01RP8",
                "scheme_name": "Sample Fund",
                "units": "2.5",
                "statement_value_inr": "250",
            }
        ]
    }

    assert not _holdings_equal(original, changed_units)
    assert not _holdings_equal(original, changed_value)
