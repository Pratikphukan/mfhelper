# Proposal: Financial Assistant MCP Server & Agent Upgrade

## 1. Objective
Transform the experimental and partially templated `agent/` folder into an intelligent, production-ready Financial Assistant and Model Context Protocol (MCP) Server. This allows conversational AI clients (Claude Desktop, Cursor, OpenCode, or terminal CLI) to interactively query fund metrics, analyze portfolio overlap, rank category funds, screen tactical dip-buying confluence signals, and inspect portfolio sheets.

---

## 2. Background & Need
Currently, `agent/mcp_server.py` contains placeholder mock documents (`deposition.md`, `report.pdf`, `financials.docx`) and generic document-editing tools inherited from an MCP boilerplate template. Only two mutual fund tools (`analyze_mutual_fund` and `read_google_sheet`) were wired in.

Meanwhile, `mfhelper` possesses extensive financial analytics engines:
- Real-time NAV & technical indicator computation (RSI-14, 200D SMA, 52W High in `mfhelper.metrics`).
- Trailing CAGR, rolling returns, Sharpe, Sortino, Calmar, and SIP XIRR (`mfhelper.returns_calc`).
- Minimum-weight portfolio overlap and stock concentration analytics (`mfhelper.overlap`).
- Multi-tier tactical confluence dip-buying and trimming alerts (`mfhelper.alerts`).

By exposing these engines through standard MCP tools, users can query their portfolio and market opportunities in natural language from their favorite AI tools or the command line.

---

## 3. Scope & Key Deliverables

1. **Purge Mock Data & Tools**:
   - Remove mock document dictionaries and mock doc tools (`read_doc_contents`, `edit_document`, `list_documents`, `get_document_content`, `rewrite`, `summarize`) from `agent/mcp_server.py`.

2. **Core Financial MCP Tools**:
   - `get_fund_metrics(scheme_code: str)`: Returns latest NAV, date, 52W high distance, 200D SMA distance, 14D Wilder RSI, and trailing CAGR (1M, 6M, 1Y, 3Y, 5Y).
   - `get_fund_overlap(code_a: str, code_b: str)`: Computes minimum-weight overlap % and shared stock holdings with portfolio weights.
   - `get_category_rankings(category: str)`: Evaluates funds in a specified category config (e.g., `flexicap`, `midcap`, `smallcap`, `multicap`, `gold_etfs`) and ranks them by Sharpe, Calmar, and trailing/rolling CAGR.
   - `screen_dip_opportunities()`: Scans all active funds in `config/funds.yaml` for Tier 1, 2, and 3 Confluence Dip-Buying signals and Trimming warnings.
   - Retain and harden `read_google_sheet(tab_name: str)` for reading live Google Sheet tabs.

3. **Standalone Module & Test Suite**:
   - Implement business logic in cleanly importable functions under `mfhelper/agent_tools.py` so both MCP server and direct scripts can invoke them.
   - Add unit tests in `tests/test_agent_tools.py` covering tool inputs, output structures, and error handling.
   - Ensure `pytest tests/` runs cleanly without test collection collisions from `agent/`.

4. **Integration & Client Configuration**:
   - Document MCP configuration snippets for Claude Desktop (`claude_desktop_config.json`), Cursor (`.cursor/mcp.json`), and OpenCode.
   - Update `agent/README.md` and project `README.md`.
