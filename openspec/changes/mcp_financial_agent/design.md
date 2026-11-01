# Design: Financial Assistant MCP Server & Agent Upgrade

## 1. Architecture Overview

```
Conversational AI Clients (Cursor [Primary], Claude Desktop, OpenCode, or CLI)
                               │ (stdio JSON-RPC via MCP)
                               ▼
                      agent/mcp_server.py (FastMCP Server)
                               │
               ┌───────────────┴───────────────┐
               ▼                               ▼
       agent/mcp_server.py            mfhelper/agent_tools.py
       (FastMCP Tool Wrappers)        (Pure Python Financial Engine)
                                               │
             ┌─────────────────┬───────────────┴───────────────┬────────────────┐
             ▼                 ▼                               ▼                ▼
     mfhelper.metrics  mfhelper.returns_calc           mfhelper.overlap  mfhelper.alerts
     (RSI, 200D, 52W)  (CAGR, Sharpe, Calmar)         (Tickertape, %s)  (Confluence Dip)
             │                 │                               │                │
             └─────────────────┴───────────────┬───────────────┴────────────────┘
                                               ▼
                                 Data Sources & Local Caches
                      (mfapi.in, yfinance, config/*.yaml, Google Sheets)
```

---

## 2. Agreed Architectural Decisions

1. **Tool Return Format Toggle**:
   - Every analytical tool supports `format: str = "markdown"` (default `"markdown"`, optional `"json"`).
   - If `"markdown"`, returns human-ready markdown tables/bullet points.
   - If `"json"`, returns indented JSON string with raw numerical values for agentic math.
2. **Category Scope**:
   - `get_category_rankings` evaluates curated funds in `config/<category>.yaml` and matching category entries in `config/funds.yaml`.
   - Ranked primarily by 3-Year Sharpe ratio (falling back to 3-Year CAGR).
3. **Primary MCP Client**:
   - Configured specifically for **Cursor** (`.cursor/mcp.json`), while remaining compatible with Claude Desktop and OpenCode.
4. **Google Sheets Permissions**:
   - Strictly read-only (`read_google_sheet`). Does not perform any write or mutate actions.

---

## 3. Tool Specifications

### Tool 1: `get_fund_metrics(scheme_code: str, format: str = "markdown") -> str`
- **Description**: Fetch real-time NAV, technical indicators (52W High distance %, 200D SMA distance %, 14D Wilder RSI), and trailing CAGR returns (1M, 6M, 1Y, 3Y, 5Y).
- **Parameters**:
  - `scheme_code`: 6-digit AMFI scheme code (e.g. `"120492"`).
  - `format`: `"markdown"` (default) for formatted tables, or `"json"` for raw numbers.
- **Output**: Formatted Markdown or serialized JSON dictionary.

### Tool 2: `get_fund_overlap(code_a: str, code_b: str, format: str = "markdown") -> str`
- **Description**: Calculate portfolio overlap percentage and list the top common stock holdings between two mutual funds.
- **Parameters**:
  - `code_a`: AMFI scheme code for fund A.
  - `code_b`: AMFI scheme code for fund B.
  - `format`: `"markdown"` (default) or `"json"`.
- **Output**: Formatted Markdown or serialized JSON dictionary.

### Tool 3: `get_category_rankings(category: str, format: str = "markdown") -> str`
- **Description**: Rank curated funds within a specific category (e.g. "flexicap", "midcap", "smallcap", "multicap", "gold_etfs") by 3Y Sharpe ratio, volatility, and trailing CAGR.
- **Parameters**:
  - `category`: Category name corresponding to `config/<category>.yaml` or category tags in `config/funds.yaml`.
  - `format`: `"markdown"` (default) or `"json"`.
- **Output**: Formatted Markdown or serialized JSON dictionary.

### Tool 4: `screen_dip_opportunities(format: str = "markdown") -> str`
- **Description**: Scan all tracked active funds in `config/funds.yaml` for active tactical dip-buying confluence signals (Tier 1 Mild, Tier 2 Moderate, Tier 3 Generational Dip) and climax trimming alerts.
- **Parameters**:
  - `format`: `"markdown"` (default) or `"json"`.
- **Output**: Formatted Markdown or serialized JSON dictionary.

### Tool 5: `read_google_sheet(tab_name: str = "", format: str = "markdown") -> str`
- **Description**: Read the contents of your Google Sheet tab (strictly read-only).
- **Parameters**:
  - `tab_name`: Name of worksheet tab.
  - `format`: `"markdown"` (default) or `"json"`.
- **Output**: Formatted Markdown table or JSON row list.

### Tool 6: `analyze_mutual_fund(scheme_code: str, format: str = "markdown") -> str`
- Backward-compatible alias for `get_fund_metrics`.

---

## 4. Cursor Integration (`.cursor/mcp.json`)

To enable instant discovery inside Cursor without manual setup:
```json
{
  "mcpServers": {
    "mfhelper": {
      "command": ".venv/bin/python",
      "args": ["agent/mcp_server.py"]
    }
  }
}
```
