# Proposal: Gold ETF Analytics Tracker & Google Sheet Writer

## 1. Objective
Introduce a dedicated **Gold ETF Analytics Tracker** (`gold_etf_main.py` and a new **`Gold ETFs Analytics`** worksheet tab in Google Sheets) that tracks, calculates, and compares performance, volatility, Sharpe/Sortino ratios, AUM, and TERs across all major Indian Gold ETFs (`GOLDBEES`, `HDFCGOLD`, `ICICIGOLD`, `AXISGOLD`, `SBIETFGOLD`, `SETFGOLD`, etc.).

---

## 2. Background & Need
While active mutual funds are evaluated on manager Alpha, Gold ETFs are passive tracking instruments that mirror physical gold prices on the stock exchange. 

As investors move towards Demat-based Gold ETF investing to eliminate AMC fund-of-funds fee drag and execution halts, having a dedicated script to compare Gold ETF trailing CAGRs, 3Y/5Y risk-adjusted ratios, expense ratios, and AUMs helps investors make data-driven choices on which Gold ETF to buy on Groww/Zerodha.

---

## 3. Scope & Exclusions
* **Gold ETFs YAML Configuration:** Create `config/gold_etfs.yaml` containing the top 8 Indian Gold ETFs with their AMFI scheme codes and ticker names.
* **Analytics Calculation Engine:** Calculate trailing performance (1Y, 3Y, 5Y), annualized standard deviation, Sharpe, Sortino, Calmar, Max Drawdown %, and TERs.
* **Dedicated Google Sheet Tab Writer:** Write and format the output table into a new, separate worksheet tab named **`Gold ETFs Analytics`** in your primary Google Sheet document.
* **Terminal Summary Table:** Print an aligned, readable ASCII summary table in the terminal console when run on demand.
