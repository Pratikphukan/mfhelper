# Design: Advanced Fund Analytics Upgrades

## 1. Architectural Data Flow
We utilize deterministic, pure-Python logic to prevent adding complex mathematical libraries.

```
[DATA SOURCE] api.mfapi.in
      │
      ▼ (result.history)
┌─────────────────────────────────────────┐
│     mfhelper.returns_calc engine        │
│  - hypothetical_sip_xirr (Bisection)   │
│  - _drawdown_analysis                   │
│  - risk_adjusted                        │
└─────────────────────┬───────────────────┘
                      ▼ (Calculated metrics)
              ┌───────────────┐
              │ AnalyticsRow  │
              └───────┬───────┘
                      ▼
┌─────────────────────────────────────────┐
│       mfhelper.analytics_sheet          │
│  - Column Mapping & Sizing              │
│  - Currency & Percent formatting        │
└─────────────────────┬───────────────────┘
                      ▼
[GOOGLE SHEETS] Tab: "Fund Analytics - Smallcap"
```

## 2. Technical Details & Algorithms

### A. SIP XIRR via Bisection Search
To solve the Internal Rate of Return (IRR) for irregular monthly cash flows without standard libraries (like scipy or numpy), we implement a robust bisection search:
* **Bracket range:** $[-99.9\%, +1000.0\%]$ annualized rate.
* **Tolerance:** Resolves down to $< 10^{-10}$ or a maximum of $120$ iterations.

### B. Calmar & Max Drawdown
* **3Y Max Drawdown:** Computed by evaluating the largest peak-to-trough drop over the trailing 365 * 3 calendar days of NAVs.
* **Calmar Ratio:** Computed as `3Y CAGR / |3Y Max Drawdown|`. If Max Drawdown is 0 or positive, Calmar returns `None`.

### C. AUM Extraction & Formatting
The Groww scraper matches the page scheme code against the requested AMFI code using raw nested `__NEXT_DATA__` JSON. The parsed AUM is extracted and written as a native floating-point number, enabling standard Google Sheet mathematical operations, and styled with:
* **Custom Number Format Pattern:** `#,##0.00` (e.g. ₹31,103.03 Cr).

---

## 3. Spreadsheet Layout & Column Formats

| Column Header | Number Format | Data Source |
| :--- | :--- | :--- |
| **Fund Name** | None (Text) | `result.scheme_name` |
| **Scheme Code** | None (Text) | `fc.code` |
| **1Y %** | `0.00%` | `analytics.py -> compute_analytics` |
| **3Y CAGR %** | `0.00%` | `analytics.py -> compute_analytics` |
| **3Y SIP %** | `0.00%` | `returns_calc.py -> hypothetical_sip_xirr` |
| **5Y CAGR %** | `0.00%` | `analytics.py -> compute_analytics` |
| **5Y SIP %** | `0.00%` | `returns_calc.py -> hypothetical_sip_xirr` |
| **7Y CAGR %** | `0.00%` | `analytics.py -> compute_analytics` |
| **10Y CAGR %** | `0.00%` | `analytics.py -> compute_analytics` |
| **SD %** | `0.00%` | `analytics.py -> compute_analytics` |
| **Sharpe** | `0.00` | `analytics.py -> compute_analytics` |
| **Sortino** | `0.00` | `analytics.py -> compute_analytics` |
| **Calmar** | `0.00` | `returns_calc.py -> risk_adjusted` |
| **Max DD (3Y) %** | `0.00%` | `returns_calc.py -> _drawdown_analysis` |
| **AUM (Cr.)** | `#,##0.00` | `expense_ratio.py -> lookup_expense_ratio` |
| **Expense %** | `0.00%` | `expense_ratio.py -> lookup_expense_ratio` |
| **Last Updated (IST)** | None (Text) | System datetime |
