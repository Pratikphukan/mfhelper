"""MFHelper Financial Assistant Model Context Protocol (MCP) Server.

Exposes native mutual fund metrics, portfolio overlap calculations, category rankings,
tactical dip/trim opportunity screening, and Google Sheets access to MCP clients
(such as Cursor, Claude Desktop, OpenCode, and the agent CLI).
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    from mcp.server.mcpserver import MCPServer as FastMCP

from pydantic import Field

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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

mcp = FastMCP("MFHelperMCP", log_level="ERROR")

CONFIG_DIR = PROJECT_ROOT / "config"


def _format_response(data: dict[str, Any], markdown_text: str, format_type: Any) -> str:
    """Format tool output as structured JSON or human-readable Markdown based on format_type."""
    fmt = getattr(format_type, "default", format_type)
    if isinstance(fmt, str) and fmt.strip().lower() == "json":
        return json.dumps(data, indent=2, default=str)
    return markdown_text


# ---------------------------------------------------------------------------
# Resources: Project Configuration Documents (Available for @ mentions)
# ---------------------------------------------------------------------------

@mcp.resource("docs://documents")
def list_documents() -> str:
    """Returns a list of all available project configuration documents."""
    valid_files = []
    if CONFIG_DIR.exists():
        for p in sorted(CONFIG_DIR.glob("*.yaml")):
            valid_files.append(p.name)
        if (CONFIG_DIR / "settings.yaml").exists():
            valid_files.append("settings.yaml")
    return json.dumps(sorted(list(set(valid_files))))


@mcp.resource("docs://documents/{doc_id}")
def get_document_content(doc_id: str) -> str:
    """Returns the content of a specific configuration file (e.g. 'funds.yaml')."""
    target = CONFIG_DIR / Path(doc_id).name
    if not target.exists() or not target.is_file():
        raise ValueError(f"Document '{doc_id}' not found in {CONFIG_DIR}")
    return target.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

@mcp.prompt()
def audit_portfolio() -> str:
    """Prompt to perform a full health check on current tracked mutual funds."""
    return (
        "Please screen all tracked funds in @funds.yaml using screen_dip_opportunities and "
        "analyze any active dip-buying or profit-trimming signals. Then evaluate whether "
        "any funds exhibit excessive overlap or drift."
    )


@mcp.prompt()
def analyze_fund(scheme_code: str) -> str:
    """Prompt to perform a complete technical and returns analysis on a single fund."""
    return (
        f"Please run get_fund_metrics for scheme code '{scheme_code}'. Evaluate its trailing CAGR, "
        "RSI momentum, distance from 52-week high, and distance from 200-day SMA. Provide an actionable summary."
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="get_fund_metrics",
    description="Fetch NAV, technical indicators (52W High distance %, 200D SMA distance %, 14D Wilder RSI), and trailing CAGR returns (1M, 6M, 1Y, 3Y, 5Y) for an AMFI scheme code."
)
def get_fund_metrics(
    scheme_code: str = Field(description="The 6-digit AMFI scheme code (e.g. '120492' for JM Flexicap, '127042' for Motilal Midcap)"),
    format: str = Field(default="markdown", description="Output format: 'markdown' for human-readable tables, or 'json' for raw structured data."),
) -> str:
    """Returns real-time fund performance, momentum indicators, and trend metrics."""
    data = fetch_fund_metrics_summary(scheme_code)
    return _format_response(data, format_metrics_markdown(data), format)


@mcp.tool(
    name="analyze_mutual_fund",
    description="Backward-compatible alias for get_fund_metrics. Analyze a mutual fund by AMFI scheme code."
)
def analyze_mutual_fund(
    scheme_code: str = Field(description="The 6-digit AMFI scheme code (e.g. '120492')"),
    format: str = Field(default="markdown", description="Output format: 'markdown' or 'json'."),
) -> str:
    """Backward-compatible alias for get_fund_metrics."""
    return get_fund_metrics(scheme_code=scheme_code, format=format)


@mcp.tool(
    name="get_fund_overlap",
    description="Calculate portfolio overlap percentage and list the top shared stock holdings between two mutual funds."
)
def get_fund_overlap(
    code_a: str = Field(description="AMFI scheme code for Fund A (e.g. '120492')"),
    code_b: str = Field(description="AMFI scheme code for Fund B (e.g. '127042')"),
    format: str = Field(default="markdown", description="Output format: 'markdown' or 'json'."),
) -> str:
    """Calculates minimum-weight pairwise portfolio intersection and shared holdings."""
    data = fetch_fund_overlap_summary(code_a, code_b)
    return _format_response(data, format_overlap_markdown(data), format)


@mcp.tool(
    name="get_category_rankings",
    description="Rank funds in a specific category (e.g. 'flexicap', 'midcap', 'smallcap', 'multicap', 'gold_etfs') by Sharpe ratio, volatility, and trailing CAGR."
)
def get_category_rankings(
    category: str = Field(description="Category name (e.g. 'flexicap', 'midcap', 'smallcap', 'multicap', 'gold_etfs')"),
    format: str = Field(default="markdown", description="Output format: 'markdown' or 'json'."),
) -> str:
    """Returns ranked comparative leaderboard for funds in a specific category."""
    data = fetch_category_rankings(category)
    return _format_response(data, format_rankings_markdown(data), format)


@mcp.tool(
    name="screen_dip_opportunities",
    description="Scan all active mutual funds in your tracked portfolio for tactical confluence dip-buying and profit-trimming signals."
)
def screen_dip_opportunities(
    format: str = Field(default="markdown", description="Output format: 'markdown' or 'json'."),
) -> str:
    """Scans tracked portfolio funds against multi-indicator technical confluence rules."""
    data = screen_dip_and_trim_opportunities()
    return _format_response(data, format_screen_markdown(data), format)


@mcp.tool(
    name="read_google_sheet",
    description="Read the contents of your Google Sheet tab (strictly read-only). If tab_name is blank, lists all available tab names in your configured spreadsheet."
)
def read_google_sheet(
    tab_name: str = Field(default="", description="The name of the worksheet tab to read (e.g. 'Daily NAV' or 'Fund Analytics'). Leave blank to list all tab names."),
    format: str = Field(default="markdown", description="Output format: 'markdown' or 'json'."),
) -> str:
    """Reads values from your configured Google Sheet and returns them formatted as a clean table."""
    import gspread
    from mfhelper.config import load_settings
    from mfhelper.sheets import _load_credentials

    settings_path = PROJECT_ROOT / "config" / "settings.yaml"
    creds_path = PROJECT_ROOT / "config" / "credentials.json"
    token_path = PROJECT_ROOT / "data" / "token.json"

    try:
        settings = load_settings(settings_path)
    except Exception as e:
        return f"Error loading settings.yaml: {e}"

    try:
        creds = _load_credentials(creds_path, token_path)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(settings.google_sheet.spreadsheet_id)
    except Exception as e:
        return f"Error connecting to Google Sheets API: {e}. Ensure credentials.json and token.json exist."

    if not tab_name.strip():
        try:
            worksheets = spreadsheet.worksheets()
            names = [w.title for w in worksheets]
            if format.strip().lower() == "json":
                return json.dumps({"worksheets": names}, indent=2)
            return "Available worksheet tabs in your Google Sheet:\n" + "\n".join([f"- {name}" for name in names])
        except Exception as e:
            return f"Error listing worksheet tabs: {e}"

    try:
        ws = spreadsheet.worksheet(tab_name.strip())
        all_values = ws.get_all_values()
    except gspread.exceptions.WorksheetNotFound:
        return f"Error: Worksheet tab '{tab_name}' not found. Please verify the name is correct."
    except Exception as e:
        return f"Error reading sheet contents: {e}"

    if not all_values:
        if format.strip().lower() == "json":
            return json.dumps({"tab_name": tab_name, "rows": []}, indent=2)
        return f"Worksheet tab '{tab_name}' is currently empty."

    max_display_rows = 50
    truncated = len(all_values) > max_display_rows
    display_rows = all_values[:max_display_rows]

    if format.strip().lower() == "json":
        return json.dumps({
            "tab_name": tab_name,
            "total_rows": len(all_values),
            "displayed_rows": len(display_rows),
            "headers": display_rows[0] if display_rows else [],
            "rows": display_rows[1:] if len(display_rows) > 1 else [],
        }, indent=2)

    lines = []
    for r_idx, row in enumerate(display_rows):
        cleaned_row = [str(cell).replace("\n", " ").strip() for cell in row]
        lines.append(" | ".join(cleaned_row))
        if r_idx == 0:
            lines.append(" | ".join(["---"] * len(row)))

    table_text = "\n".join(lines)
    if truncated:
        table_text += f"\n\n*(Table truncated: showing first {max_display_rows} of {len(all_values)} rows)*"

    return f"Contents of Google Sheet tab '{tab_name}':\n\n{table_text}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
