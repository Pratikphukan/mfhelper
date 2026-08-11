# OpenSpec: MFHelper Project Specification & Change Log

This specification document outlines the architecture, layout, core capabilities, and the evolutionary changes implemented in the **MFHelper** mutual fund tracking and analytics system.

---

## 1. System Architecture & Layout

The project is structured into three main layers: 
1. **Data Sourcing & Metrics Calculation** (`mfhelper/` internal library modules)
2. **Execution entry points** (daily scheduler and on-demand CLI analysis scripts)
3. **MCP AI Agent Layer** (Gemini/Claude compatible Model Context Protocol integration)

```
MFHelper/
  ├── main.py                    # Daily NAV scheduler (launchd)
  ├── analytics_main.py          # Category-driven analytics CLI
  ├── historical_main.py         # Historical drilldown CLI
  ├── backfill_main.py           # Historical gaps backfiller
  ├── returns_main.py            # Local JSON returns dump generator
  ├── plot_main.py               # CAGR & rolling performance plots generator
  ├── mfhelper/                  # Core modules
  │    ├── amfi.py               # AMFI text dump scraper
  │    ├── analytics.py          # Log returns, Sharpe, Sortino core
  │    ├── analytics_sheet.py    # Google Sheet Fund Analytics worksheet writer
  │    ├── metrics.py            # Day change, 52W high, 200D SMA, Wilder RSI-14
  │    ├── returns_calc.py       # Full-bouquet, SIP, and Drawdown calculations
  │    └── ...
  ├── agent/                     # Model Context Protocol (MCP) Agent
  │    ├── mcp_server.py         # MCP FastMCP server exposing tools and resources
  │    ├── mcp_client.py         # Async MCP client
  │    ├── test_agent.py         # Testing console for Agent tools
  │    └── ...
  └── config/                    # Tracked & untracked configuration
```

---

## 2. Advanced Performance & Risk Metrics

The system calculates mathematical and risk-adjusted metrics using deterministic, pure-Python logic without external heavy dependencies like NumPy or Pandas:

| Metric | Formulative Basis / Standard | Scope |
| :--- | :--- | :--- |
| **CAGR (Lumpsum)** | Annualized compounding formula over the precise days elapsed. | Long-term performance evaluation (3Y, 5Y, 7Y, 10Y). |
| **SIP XIRR** | Solved using a pure-Python bisection search on monthly cash flows (assumes ₹10k on the 1st of each month). | Realistic retail investor returns simulation. |
| **Standard Deviation (SD)** | Annualized standard deviation of daily log-returns: $\sigma_{daily} \times \sqrt{252} \times 100$. | Systematic historical volatility. |
| **Sharpe Ratio** | $(3\text{Y CAGR} - \text{Risk Free Rate}) / \sigma_{annualized}$. Risk Free Rate defaults to $7\%$. | Risk-adjusted returns relative to general volatility. |
| **Sortino Ratio** | $(3\text{Y CAGR} - \text{Risk Free Rate}) / \text{Downside Deviation}$ (ignores positive volatility). | Risk-adjusted returns relative only to negative moves. |
| **Calmar Ratio** | $3\text{Y CAGR} / \vert \text{Max Drawdown over 3Y} \vert$. | Efficiency of returns relative to worst-case peak-to-trough drop. |
| **Max Drawdown (3Y)** | Largest peak-to-trough decline over the trailing 3 years. | Worst-case historical downside risk. |

---

## 3. Evolutionary Change Log

### [August 2026] — Advanced Analytics Upgrades & AI Agent Layer

#### 1. Google Sheets Upgrades (`mfhelper/analytics_sheet.py` & `analytics_main.py`)
* **SIP Returns Integration:** Added automatic calculation and display of **3Y SIP %** and **5Y SIP %** right next to their lumpsum CAGR equivalents in the Google Sheet.
* **Risk & Efficiency Indicators:** Introduced **Calmar Ratio** and **Max Drawdown (3Y) %** columns to provide direct visibility into risk management.
* **Visual Formatting:** Upgraded column headers, conditional styles, and cell formats (such as currency formatting for AUM and percentage formatting for Drawdown/SIP).

#### 2. Category-Driven Analytics Configurations
* **Dynamic Config Paths:** Modified `analytics_main.py` to dynamically search the `config/` directory for target fund categories (e.g. running `--funds smallcap` automatically loads `config/smallcap.yaml`).
* **Automated Tab Isolation:** Sheets tab names are now derived dynamically from the config filename (e.g., writing to a tab named `Fund Analytics - Smallcap` instead of overwriting the global analytics worksheet).

#### 3. Groww AUM Extraction Scraper (`mfhelper/expense_ratio.py`)
* Updated the groww scraper to extract `aum` in crores (`aum_crore`) from the underlying JSON dump alongside `expense_ratio_pct`.
* Integrated AUM with the spreadsheet's formatting pattern: `#,##0.00`.

#### 4. AI MCP Agent Layer (`agent/`)
* Scaffolding of a custom Model Context Protocol (MCP) agent.
* **Tools exposed:**
  - `analyze_mutual_fund`: Conducts full, live returns-and-metrics analysis for any AMFI scheme code.
  - `read_google_sheet`: Dynamically connects to the user's active Google Sheet to read out cell values or list worksheet tab names.
  - Document-reading and editing utilities.
* Integrated Gemini-specific schema translation and API-key fallbacks.

#### 5. Safety & Security Enhancements
* Added `agent/.env` and any local `.env` files to `.gitignore` to strictly secure personal API keys (such as `GEMINI_API_KEY` or `ANTHROPIC_API_KEY`).
