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

import yaml

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


def _format_error(message: str, format_type: Any) -> str:
    """Format an error message as structured JSON or plain string based on format_type."""
    fmt = getattr(format_type, "default", format_type)
    if isinstance(fmt, str) and fmt.strip().lower() == "json":
        return json.dumps({"error": message}, indent=2)
    return message


def _redact_sensitive_data(val: Any) -> Any:
    """Recursively redact sensitive credential keys such as passwords, secrets, or tokens."""
    sensitive_markers = ("password", "secret", "token", "credential", "auth_key", "api_key")
    if isinstance(val, dict):
        new_dict = {}
        for k, v in val.items():
            k_lower = str(k).lower()
            if any(marker in k_lower for marker in sensitive_markers):
                new_dict[k] = "[REDACTED]" if v else v
            else:
                new_dict[k] = _redact_sensitive_data(v)
        return new_dict
    elif isinstance(val, list):
        return [_redact_sensitive_data(item) for item in val]
    return val


def _get_allowed_documents() -> list[str]:
    """Returns sorted list of allowed YAML configuration documents in CONFIG_DIR."""
    if not CONFIG_DIR.exists():
        return []
    return sorted([p.name for p in CONFIG_DIR.glob("*.yaml") if p.is_file()])


# ---------------------------------------------------------------------------
# Resources: Project Configuration Documents (Available for @ mentions)
# ---------------------------------------------------------------------------

@mcp.resource("docs://documents")
def list_documents() -> str:
    """Returns a list of all available project configuration documents."""
    return json.dumps(_get_allowed_documents())


@mcp.resource("docs://documents/{doc_id}")
def get_document_content(doc_id: str) -> str:
    """Returns the redacted content of an authorized configuration file (e.g. 'funds.yaml')."""
    allowed_docs = _get_allowed_documents()
    filename = Path(doc_id).name

    if filename not in allowed_docs or not doc_id.endswith(".yaml"):
        raise ValueError(
            f"Access denied: '{doc_id}' is not an authorized configuration document. "
            f"Allowed documents: {', '.join(allowed_docs)}"
        )

    target = (CONFIG_DIR / filename).resolve()
    try:
        target.relative_to(CONFIG_DIR.resolve())
    except ValueError:
        raise ValueError(f"Access denied: Path traversal detected in '{doc_id}'.")

    if not target.is_file():
        raise ValueError(f"Document '{doc_id}' not found in {CONFIG_DIR}")

    raw_text = target.read_text(encoding="utf-8")
    try:
        parsed = yaml.safe_load(raw_text)
        if isinstance(parsed, (dict, list)):
            redacted = _redact_sensitive_data(parsed)
            return yaml.dump(redacted, sort_keys=False)
    except Exception:
        pass

    return raw_text


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
        return _format_error(f"Error loading settings.yaml: {e}", format)

    try:
        creds = _load_credentials(creds_path, token_path)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(settings.google_sheet.spreadsheet_id)
    except Exception as e:
        return _format_error(
            f"Error connecting to Google Sheets API: {e}. Ensure credentials.json and token.json exist.",
            format,
        )

    if not tab_name.strip():
        try:
            worksheets = spreadsheet.worksheets()
            names = [w.title for w in worksheets]
            if format.strip().lower() == "json":
                return json.dumps({"worksheets": names}, indent=2)
            return "Available worksheet tabs in your Google Sheet:\n" + "\n".join([f"- {name}" for name in names])
        except Exception as e:
            return _format_error(f"Error listing worksheet tabs: {e}", format)

    try:
        ws = spreadsheet.worksheet(tab_name.strip())
        all_values = ws.get_all_values()
    except gspread.exceptions.WorksheetNotFound:
        return _format_error(f"Error: Worksheet tab '{tab_name}' not found. Please verify the name is correct.", format)
    except Exception as e:
        return _format_error(f"Error reading sheet contents: {e}", format)

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
