# OpenSpec: Advanced Fund Analytics Upgrades

This specification documents the advanced analytics enhancements implemented in the `Fund Analytics` report.

---

## 1. Objective
Provide retail mutual fund investors with more robust, risk-adjusted, and realistic performance metrics on their target list of funds to de-risk investment decision-making.

---

## 2. Advanced Metrics Implementation

### A. Lumpsum vs. SIP Comparison
* **Lumpsum CAGR:** Standard compound annual growth rate over trailing windows (3Y, 5Y).
* **SIP XIRR:** Annualized rate of return based on a hypothetical monthly contribution of ₹10,000 on the 1st of every month (using a pure-Python bisection search on cash flows).
  - *File:* `mfhelper/returns_calc.py` -> `hypothetical_sip_xirr`

### B. Downside Risk & Recovery Efficiency
* **3Y Maximum Drawdown (Max DD %):** The worst peak-to-trough drop in NAV over the trailing 3 years.
  - *File:* `mfhelper/returns_calc.py` -> `_drawdown_analysis`
* **Calmar Ratio (3Y):** Computed as `3Y CAGR / |3Y Max Drawdown|`. Highlights a fund's efficiency in recovering from historical drawdown pain.
  - *File:* `mfhelper/returns_calc.py` -> `risk_adjusted`

---

## 3. Spreadsheet Architecture Layout

The `Fund Analytics` worksheet has been horizontally expanded to include these columns:

| Column Header | Number Format | Data Source |
| :--- | :--- | :--- |
| **3Y SIP %** | `0.00%` | `returns_calc.py -> hypothetical_sip_xirr` |
| **5Y SIP %** | `0.00%` | `returns_calc.py -> hypothetical_sip_xirr` |
| **Calmar** | `0.00` | `returns_calc.py -> risk_adjusted` |
| **Max DD (3Y) %** | `0.00%` | `returns_calc.py -> _drawdown_analysis` |
| **AUM (Cr.)** | `#,##0.00` | Scraped from Groww nextData |
| **Expense %** | `0.00%` | Scraped from Groww nextData / manual override |

---

## 4. Execution & Automated Routing
Run the analytics CLI with a specific fund-list config name (located in the `config/` directory):
```bash
.venv/bin/python analytics_main.py --funds <config_name>
```
* **Tab Auto-Derivation:** The script automatically isolates different fund categories into separate worksheet tabs to prevent overwrites (e.g., `config/smallcap.yaml` compiles to `Fund Analytics - Smallcap`).
