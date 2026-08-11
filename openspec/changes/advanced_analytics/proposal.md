# Proposal: Advanced Fund Analytics Upgrades

## 1. Objective
Provide retail mutual fund investors with more robust, risk-adjusted, and realistic performance metrics on their target list of funds to de-risk investment decision-making. 

Currently, the `Fund Analytics` report only displays trailing point-to-point (lumpsum) returns and simple Sharpe ratios. For volatile categories like Small-Cap funds, this is insufficient because:
* It does not reflect realistic investment behavior (most retail investors invest via SIP).
* It does not capture extreme downside risks (drawdowns) or the efficiency of a fund in recovering from those drops (Calmar ratio).

## 2. Proposed Features

### A. Monthly SIP Simulation
Introduce **3Y SIP %** and **5Y SIP %** columns right next to the lumpsum CAGR columns. This simulates investing ₹10,000 on the 1st of every month to compute a more realistic annualized rate of return (XIRR).

### B. Downside Risk Assessment
Add **3Y Max Drawdown (Max DD %)** to show the worst peak-to-trough drop the fund suffered over the last 3 years, allowing investors to gauge if they can stomach the worst-case volatility.

### C. Recovery Efficiency
Add the **Calmar Ratio (3Y)**, defined as `3Y CAGR / |3Y Max Drawdown|`. This helps compare funds on their return-efficiency relative to the actual historical pain suffered.

### D. Scraped AUM (Crores)
Scrape and append **AUM (Cr.)** from Groww nextData as a native spreadsheet number to help investors assess fund liquidity and size.
