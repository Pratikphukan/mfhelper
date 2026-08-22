# Proposal: Interactive Performance & Risk HTML Dashboard

## 1. Objective
Introduce an **Interactive HTML Dashboard** (`dashboard_main.py` and `dashboard.html`) that parses all generated performance JSONs inside `data/fund_returns/` and renders a responsive, high-end visual dashboard with interactive charts, sliders, and summaries. This operates completely offline, requiring zero local servers or third-party paid subscriptions.

---

## 2. Background & Need
The `returns_main.py` script compiles rich, institutional-grade calculations (rolling CAGRs, SIP XIRRs, Sharpe, Sortino, Calmar ratios, and downside deviations) into git-ignored JSON files. While invaluable, reading raw JSON is difficult, and terminal-based ASCII tables have structural width constraints.

By building a self-contained HTML page using **Chart.js** (loaded securely via CDN):
1. **Interactive Charts:** Users can hover over bars and scatter points to view exact valuations, zoom in, and toggle specific funds on/off.
2. **Efficient Frontier (Risk vs. Return):** Visually maps which funds offer the highest return with the lowest risk.
3. **Seamless Portability:** The user can open `dashboard.html` in any web browser on their Mac, and it will load instantly without needing any local backend.

---

## 3. Scope & Exclusions
* **Portfolio-Wide Parser:** Write `dashboard_main.py` to recursively scan `data/fund_returns/*.json`, extract historical performance and risk-adjusted metrics, and format them into a single, unified JSON string embedded directly in the HTML template.
* **Modern Dashboard Web UI:** Build a fully responsive, modern web page styled with elegant Tailwind CSS (via CDN) and dark-mode elements.
* **Three Interactive Panels:**
  1. **Efficient Frontier (Scatter Plot):** Volunteers Annualized SD % (Risk) vs. 3Y CAGR % (Return) to visually highlight fund efficiency.
  2. **SIP Comparison (Grouped Bar Chart):** Compares 3Y, 5Y, and 10Y SIP XIRR % side-by-side.
  3. **Risk-Adjusted Ratios (Bar Chart):** Compares Sharpe (3Y), Sortino (3Y), and Calmar (3Y) scores.
* **Exclusions:** This is a read-only visual reporting script. It does not modify your Google Sheets or impact your daily background schedulers.
