# MFHelper MCP server (local stdio)

This adds a local, read-only MCP interface over MFHelper's existing calculations. It does not replace the scheduled CLI jobs, and it does not send alert emails or write to Google Sheets.

## Install

From the repository root, use the same Python environment as MFHelper:

```bash
python -m pip install -r requirements.txt
```

The existing dependency list already includes `mcp[cli]`, `pydantic`, `gspread`, and the analytics dependencies. The server imports MFHelper from the repository root, so run it using the path below rather than copying the file elsewhere.

## Run / smoke test

```bash
python agent/mfhelper_mcp_server.py
```

The process waits for MCP messages on stdin/stdout; that is expected. Do not add print-based startup banners to stdout because it is the MCP protocol stream. Logs go to stderr.

If you use the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector python agent/mfhelper_mcp_server.py
```

## Configure a local MCP client

Add a server entry to your client's MCP configuration. Example shape (adjust the absolute path to your checkout and Python executable):

```json
{
  "mcpServers": {
    "mfhelper": {
      "command": "/absolute/path/to/mfhelper/.venv/bin/python",
      "args": ["/absolute/path/to/mfhelper/agent/mfhelper_mcp_server.py"]
    }
  }
}
```

For Cursor, Claude Desktop, or another stdio-capable MCP client, use that client's local MCP configuration file and restart/reload the client after saving.

## Tools exposed

- `list_configured_funds` — configured funds and active state.
- `get_fund_analytics` — technical indicators and existing long-term return/risk analytics.
- `compare_funds` — side-by-side metrics for 2–8 scheme codes.
- `compare_fund_to_benchmark` — paired benchmark metrics using MFHelper's benchmark and comparison modules.
- `get_portfolio_overlap` — pairwise holdings overlap for 2–6 funds, using the existing AMFI/Tickertape resolution and cache.
- `evaluate_fund_alerts` — runs existing alert rules without dispatching email.
- `read_google_sheet` — lists tabs or reads a bounded number of rows; never writes.

## Local files and permissions

The tools expect your existing files where applicable:

- `config/funds.yaml`
- `config/analytics_funds.yaml` (used by the existing analytics CLI, not required for the tools above)
- `config/settings.yaml`
- `config/alerts.yaml` or `config/alerts_example.yaml`
- `config/credentials.json` and `data/token.json` for Google Sheets OAuth
- Existing local caches under `data/`

Do not commit credentials or tokens. Google Sheets access uses the OAuth scopes already defined by MFHelper; if the existing OAuth token is missing the required read scope, re-authorize locally.

## Interpretation and limitations

- Returns and indicators describe historical data and are not forecasts.
- Benchmark comparison uses the variant/data source reported by MFHelper; price-return indices exclude reinvested dividends when TRI is unavailable.
- Holdings overlap depends on third-party holdings data and fund-to-Tickertape mapping quality.
- Alert tiers are your configured heuristics, not personalized investment advice.
- All exposed tools are read-only with respect to Google Sheets and email. The overlap tool may refresh its local Tickertape mapping cache.
