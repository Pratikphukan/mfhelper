# Design: Interactive Performance & Risk HTML Dashboard

## 1. System Topology & Data Flow

The script reads your processed JSON records and bundles them into an interactive local webpage:

```
┌────────────────────────────────────────────────────────┐
│               Scan returns database                    │
│             - Path: data/fund_returns/*.json           │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼ (Parse Metrics)
┌────────────────────────────────────────────────────────┐
│             Aggregate Portfolio Dataset                │
│   Extracts:                                            │
│   - scheme_name & code                                 │
│   - 1Y, 3Y, 5Y CAGR % (Trailing)                       │
│   - 3Y, 5Y, 10Y SIP XIRR %                             │
│   - Sharpe (3Y), Sortino (3Y), Calmar (3Y)             │
│   - Annualized SD (3Y) % (Volatility/Risk)             │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼ (Inject into HTML Template)
┌────────────────────────────────────────────────────────┐
│             Generate self-contained HTML               │
│   - Writes: dashboard.html                             │
│   - Styles: Tailwind CSS (CDN)                         │
│   - Charts: Chart.js (CDN)                             │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼ (User clicks double-clicks)
              ┌──────────────────────────┐
              │  Interactive Safari/Chrome│
              │   Performance Dashboard  │
              └──────────────────────────┘
```

---

## 2. Interactive Charts Specifications

To deliver a premium, institutional-grade analytical experience, the dashboard renders three charts using **Chart.js**:

### Chart 1: The Efficient Frontier (Risk vs. Return)
* **Type:** Scatter Plot (`type: 'scatter'`)
* **X-Axis:** Annualized Standard Deviation (3Y) % — representing **Volatility (Risk)**.
* **Y-Axis:** Annualized Trailing Return (3Y) % — representing **Return**.
* **Visual Insight:** Funds positioned in the **Top-Left** (high return, low risk) are highly efficient, while funds in the **Bottom-Right** are highly inefficient.

### Chart 2: SIP Performance Comparison
* **Type:** Grouped Bar Chart (`type: 'bar'`)
* **X-Axis:** Fund Names.
* **Y-Axis:** SIP XIRR %.
* **Data series:** 3Y SIP XIRR, 5Y SIP XIRR, and 10Y SIP XIRR grouped side-by-side per fund.

### Chart 3: Risk-Adjusted Quality Rankings
* **Type:** Grouped Bar Chart (`type: 'bar'`)
* **X-Axis:** Fund Names.
* **Y-Axis:** Ratio Scores.
* **Data series:** Sharpe Ratio, Sortino Ratio, and Calmar Ratio side-by-side.

---

## 3. Web UI Styling & Theme

The webpage is designed with a modern, elegant **Light/Slate theme** utilizing **Tailwind CSS**:
* **Header block:** Incorporates clear metadata, a "Last updated" timestamp, and quick navigation filters.
* **KPI cards:** Highlight portfolio-wide best performance (e.g., Highest 3Y CAGR, Best SIP XIRR, Lowest Volatility).
* **Responsive Layout:** Grid layout that arranges charts horizontally on desktop screens and vertically on mobile/tablet viewports.
* **Hover tooltips:** Fully custom, formatted hover tooltips displaying exact percentages and labels.
