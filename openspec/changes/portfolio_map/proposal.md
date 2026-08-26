# Proposal: Consolidated Portfolio Allocation Map

## 1. Objective
Introduce a **Consolidated Portfolio Allocation Map** (`portfolio_map_main.py` and a new **`Combined Allocation`** Google Sheets tab) that aggregates your mutual fund holdings by factoring in your custom **investment weights** to compute your true, consolidated top stock holdings and sector concentrations. It also upgrades the **HTML Web Dashboard** (`dashboard.html`) to display these interactive consolidated analytics.

---

## 2. Background & Need
While users can see individual fund metrics and pairwise overlaps, there is no single consolidated view that tells them: *"Across all my mutual funds combined, what is my total exposure to HDFC Bank or the Financial Services sector?"*

This leads to "hidden concentration risk"—where investors accidentally become over-exposed to a single stock or sector because multiple funds they hold are secretly buying the same things.

By enabling the user to specify their custom investment allocation weights (e.g. 15% in SBI, 25% in JM) next to each fund in `config/funds.yaml`, we can mathematically aggregate their portfolio into a single, comprehensive asset allocation map.

---

## 3. Scope & Exclusions
* **Investment Weights Schema:** Update `FundConfig` in `mfhelper/config.py` and `config/funds.yaml` to accept an optional `weight:` floating-point field (e.g. `weight: 20.0` representing 20% of their monthly investments).
* **Consolidated Aggregator Engine:** Write `portfolio_map_main.py` to:
  * Pull down active holdings for all resolved funds from Tickertape.
  * Multiply each holding's weight inside its fund by the fund's overall weight in your portfolio.
  * Group and sum the values to compute your true consolidated top 15 stocks and sector distributions.
* **Google Sheets Synchronizer:** Automatically create and update a beautiful **`Combined Allocation`** worksheet tab in your Google Sheet, writing out your true top stocks and sector weights.
* **Interactive HTML Dashboard Upgrade:** Integrate this aggregated dataset into `dashboard_main.py` and display an interactive **Sector Distribution Donut Chart** and a **Top Stocks Bar Chart** at the top of your **`dashboard.html`**!
