# Tasks: Financial Assistant MCP Server & Agent Upgrade

This task checklist tracks the implementation of the MCP Financial Agent upgrade.

---

## Task Breakdown

### Phase 1: OpenSpec Specification
- [x] Create `proposal.md`
- [x] Create `design.md` with agreed user choices (Format toggle, Curated watchlists, Cursor integration, Read-only safety)
- [x] Create `tasks.md`
- [x] **STOP & CONFIRM GATE**: Clarify design questions with user and obtain sign-off.

### Phase 2: Core Logic & Standalone Module
- [x] Add `format: str = "markdown"` support to `agent/mcp_server.py` and `mfhelper/agent_tools.py`.
- [x] Support `"json"` serialization alongside `"markdown"` formatting for all tools:
  - [x] `get_fund_metrics`
  - [x] `get_fund_overlap`
  - [x] `get_category_rankings`
  - [x] `screen_dip_opportunities`
  - [x] `read_google_sheet`
  - [x] `analyze_mutual_fund`
- [x] Update unit tests in `tests/test_agent_tools.py` to test both `"markdown"` and `"json"` outputs.
- [x] Verify test suite passes (`pytest tests/`).

### Phase 3: Integration & Cursor Configuration
- [x] Create `.cursor/mcp.json` configuring the `mfhelper` MCP server for Cursor.
- [x] Verify Cursor configuration syntax and path resolution.

### Phase 4: CI/CD & Documentation
- [x] Ensure `.github/workflows/test.yml` remains green.
- [x] Update `agent/README.md` and project `README.md` to reflect the new `format` parameter and Cursor integration.
