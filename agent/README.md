# MFHelper Financial Assistant & MCP Server

An intelligent, conversational financial assistant and Model Context Protocol (MCP) server for mutual fund intelligence. It exposes real-time technical indicators, portfolio overlap calculations, category leaderboards, tactical dip-buying confluence scanners, and live Google Sheets access directly to AI clients.

Compatible with:
- **Claude Desktop**
- **Cursor**
- **OpenCode**
- **Interactive Terminal CLI**

---

## 🛠️ Available MCP Tools

| Tool | Parameters | Description |
| :--- | :--- | :--- |
| `get_fund_metrics` | `scheme_code` (e.g. `'120492'`), `format` (`"markdown"` \| `"json"`, default: `"markdown"`) | Real-time NAV, 52W High distance %, 200D SMA distance %, 14D Wilder RSI, and trailing CAGR (1M, 6M, 1Y, 3Y, 5Y). |
| `get_fund_overlap` | `code_a`, `code_b`, `format` (`"markdown"` \| `"json"`) | Pairwise portfolio overlap % and top common stock holdings between two funds using Tickertape. |
| `get_category_rankings` | `category` (e.g. `'flexicap'`, `'midcap'`), `format` (`"markdown"` \| `"json"`) | Ranked leaderboard sorted by 3Y Sharpe ratio, volatility (SD), and trailing CAGR. |
| `screen_dip_opportunities` | `format` (`"markdown"` \| `"json"`) | Scans tracked portfolio funds for Tier 1/2/3 Confluence Dip-Buying signals and Trimming warnings. |
| `read_google_sheet` | `tab_name` (optional), `format` (`"markdown"` \| `"json"`) | Reads any Google Sheet tab (or lists all available worksheets if omitted). |
| `analyze_mutual_fund` | `scheme_code`, `format` (`"markdown"` \| `"json"`) | Backward-compatible alias for `get_fund_metrics`. |

---

## 📄 Context Documents (`@` Mentions)

You can reference project configuration files directly in your queries using `@`:
- `@funds.yaml` - List of tracked mutual funds and categories
- `@alerts.yaml` - Technical indicator alert thresholds
- `@benchmarks.yaml` - Category benchmark assignments
- `@settings.yaml` - Google Sheet and environment settings

---

## 🚀 Usage Options

### 1. Connecting to Claude Desktop

Add the server to your `claude_desktop_config.json`:
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "mfhelper": {
      "command": "/Users/pratikphookan/PyCharmMiscProject/MFHelper/.venv/bin/python",
      "args": [
        "/Users/pratikphookan/PyCharmMiscProject/MFHelper/agent/mcp_server.py"
      ],
      "env": {
        "PYTHONPATH": "/Users/pratikphookan/PyCharmMiscProject/MFHelper"
      }
    }
  }
}
```

### 2. Connecting to Cursor

Add to `.cursor/mcp.json` in this repository or globally in `~/.cursor/mcp.json`:

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

### 3. Connecting to OpenCode

Add to your `.opencode/opencode.jsonc`:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "mfhelper": {
        "command": ".venv/bin/python",
        "args": ["agent/mcp_server.py"]
      }
    }
  }
}
```

Or run via CLI:
```bash
opencode mcp add mfhelper --command ".venv/bin/python agent/mcp_server.py"
```

### 4. Running the Interactive Terminal CLI

Run the standalone CLI chat loop:

```bash
cd /Users/pratikphookan/PyCharmMiscProject/MFHelper
.venv/bin/python agent/main.py
```

*Prerequisites for CLI mode:* Set `ANTHROPIC_API_KEY` (or `GEMINI_API_KEY`) and `CLAUDE_MODEL` in `.env` or `agent/.env`.
