"""Local stdio MCP server exposing MFHelper's existing analytics.

Run from any working directory with:
    python agent/mfhelper_mcp_server.py

This server is read-only with respect to Google Sheets and email. It may use
MFHelper's existing local data caches and Tickertape mapping cache.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mfhelper.config import load_alert_settings, load_funds, load_settings  # noqa: E402
from mfhelper.mfapi import fetch_history  # noqa: E402
from mfhelper.metrics import (  # noqa: E402
    distance_from_200d_sma,
    distance_from_52w_high,
    rsi,
)
from mfhelper.analytics import compute_analytics  # noqa: E402
from mfhelper.returns_calc import compute_fund_returns  # noqa: E402

CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
mcp = FastMCP("MFHelper", log_level="ERROR")


def _jsonable(value: Any) -> Any:
    """Convert dataclasses and date values to JSON-compatible objects."""
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _dump(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, indent=2, allow_nan=False)


def _validated_code(scheme_code: str) -> str:
    code = str(scheme_code).strip()
    if not re.fullmatch(r"\d{4,8}", code):
        raise ValueError("scheme_code must be a numeric AMFI scheme code (4-8 digits).")
    return code


def _funds(analytics: bool = False):
    path = CONFIG_DIR / ("analytics_funds.yaml" if analytics else "funds.yaml")
    return load_funds(path)


def _get_history(scheme_code: str):
    code = _validated_code(scheme_code)
    result = fetch_history(code)
    if result is None or not result.history:
        raise ValueError(f"No NAV history found for scheme code {code}. Check the AMFI code or try again later.")
    return code, result


@mcp.tool()
def list_configured_funds(include_inactive: bool = False) -> str:
    """List funds from config/funds.yaml, including code, name, category, weight and active state."""
    funds = _funds()
    if not include_inactive:
        funds = [fund for fund in funds if fund.active]
    return _dump([
        {
            "scheme_code": f.code,
            "name": f.name,
            "category": f.category,
            "weight_pct": f.weight,
            "active": f.active,
        }
        for f in funds
    ])


@mcp.tool()
def get_fund_analytics(scheme_code: str = Field(description="AMFI scheme code, e.g. 120492")) -> str:
    """Return latest NAV, RSI, distance from 52-week high and 200-day SMA, plus existing long-term return/risk analytics."""
    code, result = _get_history(scheme_code)
    history = result.history
    latest = history[0]
    analytics = compute_analytics(history)
    full_returns = compute_fund_returns(history, as_of=latest.nav_date)
    risk = full_returns.get("risk", {})
    risk_adjusted = full_returns.get("risk_adjusted", {})
    return _dump({
        "scheme_code": code,
        "scheme_name": result.scheme_name,
        "latest_nav": latest.nav,
        "nav_date": latest.nav_date,
        "history_points": len(history),
        "technical_indicators": {
            "distance_from_52w_high_pct": distance_from_52w_high(history, latest.nav, latest.nav_date),
            "distance_from_200d_sma_pct": distance_from_200d_sma(history, latest.nav, latest.nav_date),
            "rsi_14": rsi(history, latest.nav, latest.nav_date),
        },
        "analytics": analytics,
        "risk": risk,
        "risk_adjusted": risk_adjusted,
        "data_quality": full_returns.get("data_quality"),
        "notes": [
            "Metrics are historical and are not forecasts.",
            "A null metric generally means insufficient history or unavailable data.",
        ],
    })


@mcp.tool()
def compare_funds(scheme_codes: list[str] = Field(description="2-8 AMFI scheme codes to compare")) -> str:
    """Compare funds using existing return, risk, and technical indicator calculations."""
    if not 2 <= len(scheme_codes) <= 8:
        raise ValueError("Provide between 2 and 8 scheme codes.")
    normalized = [_validated_code(c) for c in scheme_codes]
    if len(set(normalized)) != len(normalized):
        raise ValueError("scheme_codes must not contain duplicates.")
    rows = []
    for code in normalized:
        _, result = _get_history(code)
        history = result.history
        latest = history[0]
        metrics = compute_analytics(history)
        returns = compute_fund_returns(history, as_of=latest.nav_date)
        rows.append({
            "scheme_code": code,
            "scheme_name": result.scheme_name,
            "latest_nav": latest.nav,
            "nav_date": latest.nav_date,
            "history_points": len(history),
            "analytics": metrics,
            "risk": returns.get("risk", {}),
            "risk_adjusted": returns.get("risk_adjusted", {}),
            "technical_indicators": {
                "distance_from_52w_high_pct": distance_from_52w_high(history, latest.nav, latest.nav_date),
                "distance_from_200d_sma_pct": distance_from_200d_sma(history, latest.nav, latest.nav_date),
                "rsi_14": rsi(history, latest.nav, latest.nav_date),
            },
        })
    return _dump({"funds": rows, "comparison_note": "Compare like-for-like plan types and fund categories; past performance does not predict future returns."})


@mcp.tool()
def compare_fund_to_benchmark(
    scheme_code: str = Field(description="AMFI scheme code"),
    benchmark_ticker: str = Field(description="Yahoo Finance ticker, e.g. ^NSEI, ^CRSLDX, ^CNX200, or GOLD_INR"),
    variant: str = "PR",
) -> str:
    """Compare fund history to an index using MFHelper's paired rolling returns, beat rate and information-ratio implementation."""
    from mfhelper.benchmarks import fetch_benchmark_history, YFINANCE_START_DATE
    from mfhelper.vs_benchmark import compute_vs_benchmark

    if variant not in {"PR", "TRI"}:
        raise ValueError("variant must be PR or TRI.")
    code, result = _get_history(scheme_code)
    ticker = benchmark_ticker.strip()
    if not ticker or len(ticker) > 40:
        raise ValueError("benchmark_ticker must be a valid short ticker string.")
    benchmark = fetch_benchmark_history(
        ticker,
        variant=variant,
        cache_dir=DATA_DIR / "benchmark_history",
        start=YFINANCE_START_DATE,
    )
    if benchmark is None or not benchmark.history:
        raise ValueError(f"No benchmark history available for {ticker}.")
    comparison = compute_vs_benchmark(
        result.history,
        benchmark.history,
        benchmark_name=ticker,
        variant=benchmark.variant,
        data_source=benchmark.data_source,
        as_of=result.history[0].nav_date,
    )
    return _dump({"scheme_code": code, "scheme_name": result.scheme_name, "comparison": comparison})


@mcp.tool()
def get_portfolio_overlap(scheme_codes: list[str] = Field(description="2-6 AMFI scheme codes for pairwise holdings overlap")) -> str:
    """Calculate pairwise stock-holdings overlap using MFHelper's Tickertape/AMFI resolver and cache."""
    from mfhelper.overlap import (
        fetch_isin_from_amfi,
        fetch_tickertape_sitemap_urls,
        resolve_mfid_by_isin,
        fetch_fund_holdings,
        calculate_overlap_percentage,
        get_tickertape_mappings_path,
        load_cached_mappings,
        save_cached_mappings,
    )

    codes = [_validated_code(c) for c in scheme_codes]
    if not 2 <= len(codes) <= 6:
        raise ValueError("Provide between 2 and 6 scheme codes.")
    if len(set(codes)) != len(codes):
        raise ValueError("scheme_codes must not contain duplicates.")
    path = get_tickertape_mappings_path()
    mappings = load_cached_mappings(path)
    code_to_isin, code_to_name = fetch_isin_from_amfi(codes)
    sitemap = None
    resolved: dict[str, str] = {}
    unresolved: list[str] = []
    for code in codes:
        isin = code_to_isin.get(code)
        if not isin:
            unresolved.append(code)
            continue
        mf_id = mappings.get(isin)
        if not mf_id:
            if sitemap is None:
                sitemap = fetch_tickertape_sitemap_urls()
            mf_id = resolve_mfid_by_isin(isin, code_to_name.get(code, ""), sitemap)
            if mf_id:
                mappings[isin] = mf_id
        if mf_id:
            resolved[code] = mf_id
        else:
            unresolved.append(code)
    save_cached_mappings(path, mappings)
    holdings = {code: fetch_fund_holdings(mf_id) for code, mf_id in resolved.items()}
    pairs = []
    for i, code_a in enumerate(codes):
        for code_b in codes[i + 1:]:
            if code_a not in holdings or code_b not in holdings:
                pairs.append({"scheme_code_a": code_a, "scheme_code_b": code_b, "overlap_pct": None, "overlapping_holdings": [], "status": "one or both fund mappings unavailable"})
                continue
            overlap_pct, details = calculate_overlap_percentage(holdings[code_a], holdings[code_b])
            pairs.append({"scheme_code_a": code_a, "scheme_code_b": code_b, "overlap_pct": overlap_pct, "overlapping_holdings": details[:30], "status": "ok"})
    return _dump({
        "fund_names_from_amfi": code_to_name,
        "pairs": pairs,
        "unresolved_scheme_codes": unresolved,
        "method_note": "Overlap uses MFHelper's minimum-weight intersection method; holdings may be dated differently across funds.",
    })


@mcp.tool()
def evaluate_fund_alerts(scheme_code: str = Field(description="AMFI scheme code")) -> str:
    """Evaluate the configured technical alert, buying-confluence and trimming rules without sending emails."""
    from mfhelper.alerts import (
        check_fund_alerts,
        check_confluence_signal,
        check_trimming_signal,
        resolve_conflicting_alerts,
    )

    code, result = _get_history(scheme_code)
    history = result.history
    latest = history[0]
    fund_cfg = next((f for f in _funds(include_inactive=True) if f.code == code), None)
    if fund_cfg is not None and not fund_cfg.active:
        return _dump({"scheme_code": code, "scheme_name": result.scheme_name, "status": "inactive", "alerts": [], "message": "This fund is marked inactive in config/funds.yaml; alerts were not evaluated."})
    alert_settings = load_alert_settings(CONFIG_DIR / "alerts.yaml")
    dist52 = distance_from_52w_high(history, latest.nav, latest.nav_date)
    dist200 = distance_from_200d_sma(history, latest.nav, latest.nav_date)
    rsi_value = rsi(history, latest.nav, latest.nav_date)
    alerts = check_fund_alerts(
        code, fund_cfg.name if fund_cfg and fund_cfg.name else result.scheme_name,
        history, latest.nav, latest.nav_date, rsi_value, dist52, dist200,
        alert_settings.rules,
    )
    resolved = resolve_conflicting_alerts(alerts)
    buying = check_confluence_signal(code, result.scheme_name, rsi_value, dist52, dist200, alert_settings.rules)
    trimming = check_trimming_signal(code, result.scheme_name, rsi_value, dist52, alert_settings.rules.rules)
    return _dump({
        "scheme_code": code,
        "scheme_name": result.scheme_name,
        "nav_date": latest.nav_date,
        "indicators": {"rsi_14": rsi_value, "distance_from_52w_high_pct": dist52, "distance_from_200d_sma_pct": dist200},
        "triggered_alerts": resolved,
        "buying_confluence_signal": buying,
        "trimming_signal": trimming,
        "email_sent": False,
        "note": "Rule outputs are heuristics, not personalized investment advice. No email was sent.",
    })


@mcp.tool()
def read_google_sheet(tab_name: str = "", max_rows: int = 100) -> str:
    """Read a configured Google Sheets tab as structured rows; blank tab_name lists tabs. This tool never writes."""
    if not 1 <= max_rows <= 500:
        raise ValueError("max_rows must be between 1 and 500.")
    import gspread
    from mfhelper.sheets import _load_credentials

    settings = load_settings(CONFIG_DIR / "settings.yaml")
    creds = _load_credentials(CONFIG_DIR / "credentials.json", DATA_DIR / "token.json")
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(settings.google_sheet.spreadsheet_id)
    if not tab_name.strip():
        return _dump({"spreadsheet": spreadsheet.title, "tabs": [ws.title for ws in spreadsheet.worksheets()]})
    try:
        worksheet = spreadsheet.worksheet(tab_name.strip())
    except gspread.exceptions.WorksheetNotFound as exc:
        raise ValueError(f"Worksheet tab {tab_name!r} was not found.") from exc
    values = worksheet.get_all_values()
    truncated = len(values) > max_rows
    values = values[:max_rows]
    headers = values[0] if values else []
    rows = [
        {headers[i] if i < len(headers) and headers[i] else f"column_{i + 1}": row[i] if i < len(row) else "" for i in range(max(len(headers), len(row)))}
        for row in values[1:]
    ]
    return _dump({"spreadsheet": spreadsheet.title, "tab": worksheet.title, "headers": headers, "rows": rows, "rows_returned": len(rows), "truncated": truncated, "read_only": True})


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR, stream=sys.stderr)
    mcp.run(transport="stdio")
