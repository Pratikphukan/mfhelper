"""Unit tests for mfhelper.agent_tools module."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mfhelper.agent_tools import (
    fetch_category_rankings,
    fetch_fund_metrics_summary,
    fetch_fund_overlap_summary,
    format_metrics_markdown,
    format_overlap_markdown,
    format_rankings_markdown,
    format_screen_markdown,
    screen_dip_and_trim_opportunities,
)
from mfhelper.config import FundConfig
from mfhelper.mfapi import MfapiResult, NavHistoryPoint
from mfhelper.overlap import HoldingItem


def _make_dummy_history(count: int = 300, start_nav: float = 100.0) -> list[NavHistoryPoint]:
    """Generate mock NAV history (newest first)."""
    base_date = date(2026, 5, 1)
    pts = []
    current_nav = start_nav
    for i in range(count):
        d = base_date - timedelta(days=i)
        pts.append(NavHistoryPoint(nav_date=d, nav=current_nav))
        current_nav -= 0.1  # slightly downward in past, so current is highest
    return pts


# ---------------------------------------------------------------------------
# Fund Metrics Tests
# ---------------------------------------------------------------------------

def test_fetch_fund_metrics_summary_success():
    history = _make_dummy_history(250, 150.0)
    mock_result = MfapiResult(scheme_name="Test Growth Fund", history=history)

    with patch("mfhelper.agent_tools.fetch_history", return_value=mock_result):
        res = fetch_fund_metrics_summary("120492")

    assert res["status"] == "success"
    assert res["scheme_code"] == "120492"
    assert res["scheme_name"] == "Test Growth Fund"
    assert res["latest_nav"] == 150.0
    assert "dist_52w_high_pct" in res
    assert "dist_200d_sma_pct" in res
    assert "rsi_14" in res
    assert "trailing_returns" in res


def test_fetch_fund_metrics_summary_not_found():
    with patch("mfhelper.agent_tools.fetch_history", return_value=None):
        res = fetch_fund_metrics_summary("999999")

    assert res["status"] == "error"
    assert "No NAV history found" in res["message"]


def test_format_metrics_markdown():
    data = {
        "status": "success",
        "scheme_code": "120492",
        "scheme_name": "Test Flexicap Fund",
        "latest_nav": 125.45,
        "latest_date": "2026-05-01",
        "dist_52w_high_pct": -2.3,
        "dist_200d_sma_pct": 5.4,
        "rsi_14": 45.2,
        "trailing_returns": {"1M": 2.1, "1Y": 18.5, "3Y": 22.4},
    }
    md = format_metrics_markdown(data)
    assert "### 📊 Fund Analytics: Test Flexicap Fund (`120492`)" in md
    assert "₹125.4500" in md
    assert "-2.30%" in md
    assert "+18.50%" in md


def test_format_metrics_markdown_error():
    data = {"status": "error", "message": "Fund not found"}
    md = format_metrics_markdown(data)
    assert "❌ Fund not found" in md


# ---------------------------------------------------------------------------
# Overlap Tests
# ---------------------------------------------------------------------------

def test_fetch_fund_overlap_summary_identical_codes():
    res = fetch_fund_overlap_summary("120492", "120492")
    assert res["status"] == "error"
    assert "identical" in res["message"]


def test_fetch_fund_overlap_summary_success():
    holdings_a = [
        HoldingItem(company_name="HDFC Bank", allocation_pct=9.0, sid="HDF", ticker="HDFCBANK", instrument_type="Equity"),
        HoldingItem(company_name="Reliance Industries", allocation_pct=8.0, sid="REL", ticker="RELIANCE", instrument_type="Equity"),
        HoldingItem(company_name="Infosys", allocation_pct=5.0, sid="INF", ticker="INFY", instrument_type="Equity"),
    ]
    holdings_b = [
        HoldingItem(company_name="HDFC Bank", allocation_pct=6.0, sid="HDF", ticker="HDFCBANK", instrument_type="Equity"),
        HoldingItem(company_name="Reliance Industries", allocation_pct=7.0, sid="REL", ticker="RELIANCE", instrument_type="Equity"),
        HoldingItem(company_name="TCS", allocation_pct=4.0, sid="TCS", ticker="TCS", instrument_type="Equity"),
    ]

    with patch("mfhelper.overlap.fetch_isin_from_amfi", return_value=(
        {"1001": "INF1001", "1002": "INF1002"},
        {"1001": "Fund A", "1002": "Fund B"},
    )), \
         patch("mfhelper.overlap.load_cached_mappings", return_value={"INF1001": "fund-a", "INF1002": "fund-b"}), \
         patch("mfhelper.overlap.fetch_fund_holdings", side_effect=[holdings_a, holdings_b]):

        res = fetch_fund_overlap_summary("1001", "1002")

    assert res["status"] == "success"
    assert res["fund_a"]["name"] == "Fund A"
    assert res["fund_b"]["name"] == "Fund B"
    # min(9, 6) + min(8, 7) = 6 + 7 = 13%
    assert pytest.approx(res["overlap_pct"], 0.1) == 13.0
    assert res["common_count"] == 2

    # Verify Markdown formatting with actual summary output directly from fetch_fund_overlap_summary
    md = format_overlap_markdown(res)
    assert "### 🗺️ Portfolio Overlap Analysis" in md
    assert "13.00%" in md
    assert "HDFC Bank" in md
    assert "Reliance Industries" in md
    assert "Unknown" not in md
    assert "**6.00%**" in md
    assert "**7.00%**" in md


def test_format_overlap_markdown():
    data = {
        "status": "success",
        "fund_a": {"code": "1001", "name": "Alpha Fund", "total_holdings": 40},
        "fund_b": {"code": "1002", "name": "Beta Fund", "total_holdings": 50},
        "overlap_pct": 35.5,
        "common_count": 12,
        "common_stocks": [
            {"company_name": "HDFC Bank", "intersection": 6.5, "alloc_a": 8.0, "alloc_b": 6.5},
        ],
    }
    md = format_overlap_markdown(data)
    assert "### 🗺️ Portfolio Overlap Analysis" in md
    assert "35.50%" in md
    assert "Moderate Overlap" in md
    assert "HDFC Bank" in md
    assert "Unknown" not in md


# ---------------------------------------------------------------------------
# Category Rankings Tests
# ---------------------------------------------------------------------------

def test_fetch_category_rankings_not_found(tmp_path):
    with patch("mfhelper.agent_tools.CONFIG_DIR", tmp_path):
        res = fetch_category_rankings("nonexistent_cat")
    assert res["status"] == "error"
    assert "not found" in res["message"]


def test_fetch_category_rankings_success(tmp_path):
    cat_yaml = tmp_path / "flexicap.yaml"
    cat_yaml.write_text("funds:\n  - code: '1001'\n    name: 'Fund 1'\n  - code: '1002'\n    name: 'Fund 2'\n")

    history_1 = _make_dummy_history(400, 100.0)
    history_2 = _make_dummy_history(400, 200.0)

    res_1 = MfapiResult(scheme_name="Fund 1", history=history_1)
    res_2 = MfapiResult(scheme_name="Fund 2", history=history_2)

    with patch("mfhelper.agent_tools.CONFIG_DIR", tmp_path), \
         patch("mfhelper.agent_tools.fetch_history", side_effect=[res_1, res_2]):

        res = fetch_category_rankings("flexicap")

    assert res["status"] == "success"
    assert res["category"] == "flexicap"
    assert res["count"] == 2
    assert len(res["rankings"]) == 2
    # Verify trailing return fields are properly populated from trailing_returns engine keys
    assert res["rankings"][0]["cagr_1y"] is not None


def test_fetch_category_rankings_gold_etfs(tmp_path):
    # Tests loading category file using etfs: schema (like config/gold_etfs.yaml)
    cat_yaml = tmp_path / "gold_etfs.yaml"
    cat_yaml.write_text("etfs:\n  - code: '140088'\n    ticker: 'GOLDBEES'\n    name: 'Nippon Gold ETF'\n")

    history = _make_dummy_history(400, 50.0)
    mock_res = MfapiResult(scheme_name="Nippon Gold ETF", history=history)

    with patch("mfhelper.agent_tools.CONFIG_DIR", tmp_path), \
         patch("mfhelper.agent_tools.fetch_history", return_value=mock_res):

        res = fetch_category_rankings("gold_etfs")

    assert res["status"] == "success"
    assert res["category"] == "gold_etfs"
    assert res["count"] == 1
    assert res["rankings"][0]["code"] == "140088"
    assert res["rankings"][0]["name"] == "Nippon Gold ETF"
    assert res["rankings"][0]["cagr_1y"] is not None


def test_format_rankings_markdown():
    data = {
        "status": "success",
        "category": "flexicap",
        "count": 2,
        "rankings": [
            {
                "code": "1001",
                "name": "Parag Parikh Flexi Cap",
                "cagr_1y": 24.5,
                "cagr_3y": 19.8,
                "cagr_5y": 21.2,
                "sharpe_3y": 1.45,
                "sd_3y": 12.1,
            },
        ],
    }
    md = format_rankings_markdown(data)
    assert "### 🏆 Category Rankings: FLEXICAP" in md
    assert "Parag Parikh Flexi Cap" in md
    assert "1.45" in md


# ---------------------------------------------------------------------------
# Dip & Trim Scanner Tests
# ---------------------------------------------------------------------------

def test_screen_dip_and_trim_opportunities_clean(tmp_path):
    funds_yaml = tmp_path / "funds.yaml"
    funds_yaml.write_text("funds:\n  - code: '1001'\n    name: 'Fund One'\n    active: true\n")

    # Steady NAV so no dip or trim triggers
    history = _make_dummy_history(250, 100.0)
    mock_res = MfapiResult(scheme_name="Fund One", history=history)

    with patch("mfhelper.agent_tools.fetch_history", return_value=mock_res), \
         patch("mfhelper.alerts.check_confluence_signal", return_value=None), \
         patch("mfhelper.alerts.check_trimming_signal", return_value=None):

        res = screen_dip_and_trim_opportunities(funds_path=funds_yaml)

    assert res["status"] == "success"
    assert res["scanned_count"] == 1
    assert len(res["dip_signals"]) == 0
    assert len(res["trim_signals"]) == 0

    md = format_screen_markdown(res)
    assert "No extreme dip or trim confluences detected today" in md


def test_screen_dip_and_trim_opportunities_with_signals(tmp_path):
    funds_yaml = tmp_path / "funds.yaml"
    funds_yaml.write_text("funds:\n  - code: '1001'\n    name: 'Fund One'\n    active: true\n")

    from mfhelper.alerts import DipBuyingSignal

    sig = DipBuyingSignal(
        scheme_code="1001",
        fund_name="Fund One",
        tier=3,
        reasons=["RSI is 28.5 (Oversold)", "52W Drop is -22.0% (Deep)"],
        suggestion="Strong Confluence Buy. Aggressive lumpsum top-up.",
        groww_link="https://groww.in/mutual-funds/search?q=Fund+One",
    )

    history = _make_dummy_history(250, 100.0)
    mock_res = MfapiResult(scheme_name="Fund One", history=history)

    with patch("mfhelper.agent_tools.fetch_history", return_value=mock_res), \
         patch("mfhelper.alerts.check_confluence_signal", return_value=sig), \
         patch("mfhelper.alerts.check_trimming_signal", return_value=None):

        res = screen_dip_and_trim_opportunities(funds_path=funds_yaml)

    assert res["status"] == "success"
    assert len(res["dip_signals"]) == 1
    assert res["dip_signals"][0]["tier"] == 3

    md = format_screen_markdown(res)
    assert "Tier-3 Generational Dip" in md
    assert "Fund One" in md
    assert "Direct Buy on Groww" in md


def test_screen_dip_and_trim_opportunities_all_failed(tmp_path):
    funds_yaml = tmp_path / "funds.yaml"
    funds_yaml.write_text("funds:\n  - code: '1001'\n    name: 'Fund One'\n    active: true\n")

    # When network/API fails for all funds
    with patch("mfhelper.agent_tools.fetch_history", return_value=None):
        res = screen_dip_and_trim_opportunities(funds_path=funds_yaml)

    assert res["status"] == "error"
    assert res["active_evaluated_count"] == 0
    assert len(res["failed_funds"]) == 1
    assert res["failed_funds"][0]["code"] == "1001"

    md = format_screen_markdown(res)
    assert "❌ Could not retrieve NAV history" in md
    assert "Failed funds: Fund One (`1001`)" in md


def test_screen_dip_and_trim_opportunities_partial_failed(tmp_path):
    funds_yaml = tmp_path / "funds.yaml"
    funds_yaml.write_text("funds:\n  - code: '1001'\n    name: 'Fund One'\n    active: true\n  - code: '1002'\n    name: 'Fund Two'\n    active: true\n")

    history = _make_dummy_history(250, 100.0)
    mock_res = MfapiResult(scheme_name="Fund One", history=history)

    # Fund 1 succeeds, Fund 2 fails
    with patch("mfhelper.agent_tools.fetch_history", side_effect=[mock_res, None]), \
         patch("mfhelper.alerts.check_confluence_signal", return_value=None), \
         patch("mfhelper.alerts.check_trimming_signal", return_value=None):

        res = screen_dip_and_trim_opportunities(funds_path=funds_yaml)

    assert res["status"] == "success"
    assert res["active_evaluated_count"] == 1
    assert len(res["failed_funds"]) == 1
    assert res["failed_funds"][0]["code"] == "1002"

    md = format_screen_markdown(res)
    assert "Evaluated **1 active funds**" in md
    assert "Could not retrieve data for 1 fund(s): Fund Two" in md


# ---------------------------------------------------------------------------
# Format Toggle & MCP Server Wrapper Tests
# ---------------------------------------------------------------------------

def test_mcp_server_format_response_toggle():
    import json
    from agent.mcp_server import _format_response

    sample_dict = {"status": "success", "metric": 42.5}
    md_str = "### Metric: 42.5"

    # Default / markdown
    res_md = _format_response(sample_dict, md_str, "markdown")
    assert res_md == md_str

    # JSON toggle
    res_json = _format_response(sample_dict, md_str, "json")
    parsed = json.loads(res_json)
    assert parsed["metric"] == 42.5


def test_get_fund_metrics_mcp_json():
    import json
    from agent.mcp_server import get_fund_metrics

    history = _make_dummy_history(250, 150.0)
    mock_result = MfapiResult(scheme_name="Test Growth Fund", history=history)

    with patch("mfhelper.agent_tools.fetch_history", return_value=mock_result):
        # Test markdown format (default)
        md_out = get_fund_metrics("120492")
        assert "### 📊 Fund Analytics:" in md_out

        # Test JSON format
        json_out = get_fund_metrics("120492", format="json")
        data = json.loads(json_out)
        assert data["status"] == "success"
        assert data["latest_nav"] == 150.0


def test_get_fund_overlap_mcp_json():
    import json
    from agent.mcp_server import get_fund_overlap

    holdings_a = [HoldingItem("HDFC Bank", 10.0, "HDF", "HDFCBANK", "Equity")]
    holdings_b = [HoldingItem("HDFC Bank", 8.0, "HDF", "HDFCBANK", "Equity")]

    with patch("mfhelper.overlap.fetch_isin_from_amfi", return_value=(
        {"1001": "INF1001", "1002": "INF1002"},
        {"1001": "Fund A", "1002": "Fund B"},
    )), \
         patch("mfhelper.overlap.load_cached_mappings", return_value={"INF1001": "fund-a", "INF1002": "fund-b"}), \
         patch("mfhelper.overlap.fetch_fund_holdings", side_effect=[holdings_a, holdings_b]):

        json_out = get_fund_overlap("1001", "1002", format="json")
        data = json.loads(json_out)
        assert data["status"] == "success"
        assert data["overlap_pct"] == 8.0


def test_get_category_rankings_mcp_json(tmp_path):
    import json
    from agent.mcp_server import get_category_rankings

    cat_yaml = tmp_path / "midcap.yaml"
    cat_yaml.write_text("funds:\n  - code: '1001'\n    name: 'Midcap Fund 1'\n")

    history = _make_dummy_history(400, 100.0)
    res = MfapiResult(scheme_name="Midcap Fund 1", history=history)

    with patch("mfhelper.agent_tools.CONFIG_DIR", tmp_path), \
         patch("mfhelper.agent_tools.fetch_history", return_value=res):

        json_out = get_category_rankings("midcap", format="json")
        data = json.loads(json_out)
        assert data["status"] == "success"
        assert data["category"] == "midcap"
        assert len(data["rankings"]) == 1


def test_screen_dip_opportunities_mcp_json(tmp_path):
    import json
    from agent.mcp_server import screen_dip_opportunities

    funds_yaml = tmp_path / "funds.yaml"
    funds_yaml.write_text("funds:\n  - code: '1001'\n    name: 'Fund 1'\n    active: true\n")

    history = _make_dummy_history(250, 100.0)
    res = MfapiResult(scheme_name="Fund 1", history=history)

    with patch("agent.mcp_server.PROJECT_ROOT", tmp_path), \
         patch("agent.mcp_server.CONFIG_DIR", tmp_path), \
         patch("mfhelper.agent_tools.CONFIG_DIR", tmp_path), \
         patch("mfhelper.agent_tools.fetch_history", return_value=res), \
         patch("mfhelper.alerts.check_confluence_signal", return_value=None), \
         patch("mfhelper.alerts.check_trimming_signal", return_value=None):

        json_out = screen_dip_opportunities(format="json")
        data = json.loads(json_out)
        assert data["status"] == "success"
        assert data["scanned_count"] == 1


def test_mcp_server_document_redaction(tmp_path):
    from agent.mcp_server import get_document_content

    alerts_yaml = tmp_path / "alerts.yaml"
    alerts_yaml.write_text(
        "rules:\n  rsi_lower_threshold: 30.0\n"
        "email:\n  enable: true\n  sender_email: test@example.com\n  sender_password: secret_password_123\n"
    )

    with patch("agent.mcp_server.CONFIG_DIR", tmp_path):
        content = get_document_content("alerts.yaml")

    assert "secret_password_123" not in content
    assert "[REDACTED]" in content
    assert "test@example.com" in content


def test_mcp_server_document_security_restrictions(tmp_path):
    import pytest
    from agent.mcp_server import get_document_content

    # Disallowed non-yaml file
    creds_json = tmp_path / "credentials.json"
    creds_json.write_text('{"token": "super_secret"}')

    with patch("agent.mcp_server.CONFIG_DIR", tmp_path):
        with pytest.raises(ValueError, match="Access denied"):
            get_document_content("credentials.json")

        with pytest.raises(ValueError, match="Access denied"):
            get_document_content("../secret.yaml")


def test_read_google_sheet_json_errors(tmp_path):
    import json
    from agent.mcp_server import read_google_sheet

    # When settings.yaml is missing
    with patch("agent.mcp_server.PROJECT_ROOT", tmp_path):
        out = read_google_sheet("Sheet1", format="json")
        parsed = json.loads(out)
        assert "error" in parsed
        assert "Error loading settings.yaml" in parsed["error"]


def test_mcp_client_read_resource():
    import asyncio
    from agent.mcp_client import MCPClient
    from unittest.mock import AsyncMock, MagicMock

    async def _run():
        client = MCPClient(command="dummy", args=[])
        mock_session = MagicMock()

        # Test list of documents
        doc_result = MagicMock()
        doc_content = MagicMock()
        doc_content.text = '["funds.yaml", "alerts.yaml"]'
        doc_result.contents = [doc_content]
        mock_session.read_resource = AsyncMock(return_value=doc_result)
        client._session = mock_session

        docs = await client.read_resource("docs://documents")
        assert isinstance(docs, list)
        assert "funds.yaml" in docs

        # Test single document content
        content_result = MagicMock()
        file_content = MagicMock()
        file_content.text = "funds:\n  - code: '120492'\n"
        content_result.contents = [file_content]
        mock_session.read_resource = AsyncMock(return_value=content_result)

        text = await client.read_resource("docs://documents/funds.yaml")
        assert isinstance(text, str)
        assert "120492" in text

    asyncio.run(_run())

