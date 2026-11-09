from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mfhelper.analytics_sheet import _COLUMN_FORMATS, HEADERS, AnalyticsRow
from mfhelper.aum import (
    fetch_amfi_quarterly_aaum,
    format_quarter_calendar,
    get_quarterly_aaum,
)


def test_format_quarter_calendar():
    assert format_quarter_calendar("July - September 2026") == "Jul-Sep 2026"
    assert format_quarter_calendar("April - June 2026") == "Apr-Jun 2026"
    assert format_quarter_calendar("January - March 2026") == "Jan-Mar 2026"
    assert format_quarter_calendar("October - December 2025") == "Oct-Dec 2025"
    assert format_quarter_calendar("July-September 2026") == "Jul-Sep 2026"
    assert format_quarter_calendar("Unknown format") == "Unknown format"
    assert format_quarter_calendar("") == ""


def test_headers_and_column_formats_alignment():
    assert len(HEADERS) == len(_COLUMN_FORMATS)
    aum_idx = HEADERS.index("AUM (Cr.)")
    quarter_idx = HEADERS.index("AUM Quarter")
    assert quarter_idx == aum_idx + 1
    assert _COLUMN_FORMATS[quarter_idx] is None  # Plain text


def test_analytics_row_to_cells_with_aum_quarter():
    now = datetime(2026, 11, 9, 10, 30, 0)
    row = AnalyticsRow(
        fund_name="Test Flexi Cap",
        scheme_code="120492",
        return_1y_abs_pct=24.5,
        cagr_3y_pct=18.2,
        sip_3y_pct=16.5,
        cagr_5y_pct=20.1,
        sip_5y_pct=18.0,
        cagr_7y_pct=17.5,
        cagr_10y_pct=16.0,
        sd_pct=12.4,
        sharpe=1.45,
        sortino=2.10,
        calmar_3y=1.85,
        max_dd_3y_pct=-10.2,
        aum_crore=2337.33,
        aum_quarter="Jul-Sep 2026",
        expense_pct=0.75,
        last_updated_ist=now,
    )

    cells = row.to_cells()
    assert len(cells) == len(HEADERS)
    assert cells[HEADERS.index("AUM (Cr.)")] == 2337.33
    assert cells[HEADERS.index("AUM Quarter")] == "Jul-Sep 2026"


def test_analytics_row_to_cells_blank_aum_quarter():
    now = datetime(2026, 11, 9, 10, 30, 0)
    row = AnalyticsRow(
        fund_name="Test Flexi Cap",
        scheme_code="120492",
        return_1y_abs_pct=None,
        cagr_3y_pct=None,
        sip_3y_pct=None,
        cagr_5y_pct=None,
        sip_5y_pct=None,
        cagr_7y_pct=None,
        cagr_10y_pct=None,
        sd_pct=None,
        sharpe=None,
        sortino=None,
        calmar_3y=None,
        max_dd_3y_pct=None,
        aum_crore=None,
        aum_quarter=None,
        expense_pct=None,
        last_updated_ist=now,
    )

    cells = row.to_cells()
    assert cells[HEADERS.index("AUM (Cr.)")] == ""
    assert cells[HEADERS.index("AUM Quarter")] == ""


def test_fetch_amfi_quarterly_aaum_success():
    mock_session = MagicMock()

    res_years = MagicMock()
    res_years.json.return_value = {
        "data": [{"id": 1, "financial_year": "April 2026 - March 2027"}]
    }

    res_periods = MagicMock()
    res_periods.json.return_value = {
        "data": {
            "periods": [{"id": 1, "period": "July - September 2026"}]
        }
    }

    res_schemes = MagicMock()
    res_schemes.json.return_value = {
        "data": [
            {
                "schemes": [
                    {
                        "AMFI_Code": 120492,
                        "AverageAumForTheMonth": {
                            "ExcludingFundOfFundsDomesticButIncludingFundOfFundsOverseas": 233733.38,
                            "FundOfFundsDomestic": 0,
                        },
                    },
                    {
                        "AMFI_Code": 127042,
                        "AverageAumForTheMonth": {
                            "ExcludingFundOfFundsDomesticButIncludingFundOfFundsOverseas": 2460925.72,
                            "FundOfFundsDomestic": 0,
                        },
                    },
                ]
            }
        ]
    }

    mock_session.get.side_effect = [res_years, res_periods, res_schemes]

    aum_by_code, quarter_label = fetch_amfi_quarterly_aaum(session=mock_session)

    assert quarter_label == "Jul-Sep 2026"
    assert aum_by_code["120492"] == 2337.33
    assert aum_by_code["127042"] == 24609.26

    # Verify that all 3 calls use the schemewise endpoint
    for call in mock_session.get.call_args_list:
        assert "average-aum-schemewise" in call[0][0]


def test_fetch_amfi_quarterly_aaum_preserves_zero_aum():
    mock_session = MagicMock()
    mock_session.get.side_effect = [
        MagicMock(json=lambda: {"data": [{"id": 1}]}),
        MagicMock(json=lambda: {"data": {"periods": [{"id": 1, "period": "July - September 2026"}]}}),
        MagicMock(json=lambda: {
            "data": [
                {
                    "schemes": [
                        {
                            "AMFI_Code": 199999,
                            "AverageAumForTheMonth": {
                                "ExcludingFundOfFundsDomesticButIncludingFundOfFundsOverseas": 0.0,
                                "FundOfFundsDomestic": 0.0,
                            },
                        }
                    ]
                }
            ]
        }),
    ]

    aum_by_code, _ = fetch_amfi_quarterly_aaum(session=mock_session)
    assert aum_by_code["199999"] == 0.0


def test_get_quarterly_aaum_handles_malformed_cache(tmp_path):
    cache_file = tmp_path / "quarterly_aaum.json"

    # Malformed cases: list instead of dict, or aum_by_code not a dict
    for bad_content in ("[]", '{"aum_by_code": ["not-a-dict"]}', '{"aum_by_code": 123}'):
        cache_file.write_text(bad_content, encoding="utf-8")
        with patch("mfhelper.aum.fetch_amfi_quarterly_aaum", side_effect=Exception("Network error")):
            aum_by_code, quarter_label = get_quarterly_aaum(cache_path=cache_file)
            assert aum_by_code == {}
            assert quarter_label is None


def test_get_quarterly_aaum_cached(tmp_path):
    cache_file = tmp_path / "quarterly_aaum.json"
    cache_file.write_text(
        """{
          "fetched_at": "2026-11-09T00:00:00+00:00",
          "quarter_label": "Jul-Sep 2026",
          "aum_by_code": {
            "120492": 2337.33
          }
        }""",
        encoding="utf-8",
    )

    with patch("mfhelper.aum.fetch_amfi_quarterly_aaum") as mock_fetch:
        aum_by_code, quarter_label = get_quarterly_aaum(cache_path=cache_file, max_age_days=7)
        mock_fetch.assert_not_called()

    assert quarter_label == "Jul-Sep 2026"
    assert aum_by_code["120492"] == 2337.33


def test_get_quarterly_aaum_fallback_on_network_failure(tmp_path):
    cache_file = tmp_path / "quarterly_aaum.json"
    cache_file.write_text(
        """{
          "fetched_at": "2026-10-01T00:00:00+00:00",
          "quarter_label": "Apr-Jun 2026",
          "aum_by_code": {
            "120492": 2100.00
          }
        }""",
        encoding="utf-8",
    )

    with patch("mfhelper.aum.fetch_amfi_quarterly_aaum", side_effect=Exception("Network error")):
        aum_by_code, quarter_label = get_quarterly_aaum(cache_path=cache_file, force_refresh=True)

    assert quarter_label == "Apr-Jun 2026"
    assert aum_by_code["120492"] == 2100.00
