# OpenSpec: Advanced Fund Analytics Upgrades

This specification documents the advanced analytics enhancements implemented in the `Fund Analytics` report.

---

## 1. Objective
Provide retail mutual fund investors with more robust, risk-adjusted, and realistic performance metrics on their target list of funds to de-risk investment decision-making.

---

## 2. Design & Architecture Proposal

The goal is to expand the existing point-to-point trailing returns sheet into a comprehensive risk-and-performance matrix. 

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

### Key Design Considerations:
1. **SIP XIRR via Bisection:** To avoid adding complex math library dependencies (like `scipy` or `numpy`), we use a pure-Python bisection search on monthly cash flows. This ensures that the code remains lightweight and portable while remaining highly accurate (solving down to $< 10^{-10}$ tolerance).
2. **AUM Scrape and Pattern Formatting:** The Groww `__NEXT_DATA__` scraper has been extended to parse and return `aum_crore`. This needs to be written to Google Sheets as a native numeric float but styled with a customized currency number format pattern (`#,##0.00`) to enable spreadsheet filtering.
3. **Calmar vs. Sharpe:** Calmar strictly uses the maximum peak-to-trough drop rather than symmetric volatility (Standard Deviation). This is critical for evaluating small-cap managers who may run high-volatility portfolios but avoid devastating drawdown events.

---

## 3. Spreadsheet Layout & Formats

The `Fund Analytics` worksheet has been horizontally expanded to include these columns:

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

---

## 4. Implementation Tasks

### Task 1: Scraper Extension
* [x] Modify `mfhelper/expense_ratio.py` -> `ExpenseRatioResult` to hold `aum_crore`.
* [x] Parse `aum` in crores from `__NEXT_DATA__` and round it to 2 decimal places.

### Task 2: Data Structure Refactoring
* [x] Update `AnalyticsRow` dataclass in `mfhelper/analytics_sheet.py` to support `sip_3y_pct`, `sip_5y_pct`, `calmar_3y`, and `max_dd_3y_pct`.
* [x] Extend the global `HEADERS` tuple and adjust `_COLUMN_FORMATS` mapping to align precisely.
* [x] Update `to_cells()` to serialize the new fields, replacing `None` with `""` for formatting.

### Task 3: Orchestrator Integration
* [x] Update `analytics_main.py` imports to include `hypothetical_sip_xirr`, `_drawdown_analysis`, and `risk_adjusted` from `mfhelper.returns_calc`.
* [x] Fetch the `as_of` date dynamically from the newest point in `result.history`.
* [x] Compute trailing 3-year history subset for Max Drawdown evaluation.
* [x] Populate the newly added fields inside the `AnalyticsRow` generation loop.

### Task 4: CLI Verification
* [x] Verify calculations run cleanly in dry-run mode.
* [x] Confirm that Google Sheet table creation, header styling, and column formats are atomic and error-free.
