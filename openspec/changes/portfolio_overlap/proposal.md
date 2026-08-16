# Proposal: Standalone Mutual Fund Portfolio Overlap Analyzer

## 1. Objective
Introduce a standalone command-line analysis tool, `overlap_main.py`, that computes the pairwise stock holding overlaps between all mutual funds configured inside `config/funds.yaml`. This enables users to audit hidden concentration risks and ensure their portfolio is genuinely diversified rather than overlapping.

---

## 2. Background & Need
A common trap in mutual fund investing is holding multiple funds (e.g., a Flexicap fund and an ELSS fund) that secretly invest in the exact same underlying large-cap stocks (e.g., HDFC Bank, ICICI Bank, Reliance). This is known as "portfolio overlap."

Because standard public APIs (like AMFI and `mfapi.in`) only provide historical NAV prices rather than underlying equity portfolios, we need a reliable, free, and non-intrusive way to:
1. Map AMFI scheme codes to live equity holdings.
2. Calculate the intersection of holding weights.
3. Present the data as an actionable, readable report.

---

## 3. Scope & Exclusions
* **Scope:** 
  * Parse local `config/funds.yaml` and resolve ISINs using AMFI's daily file.
  * Dynamically map ISINs to Tickertape ID codes (`mfId`) using an automated, fuzzy-name-sorted sitemap lookup and verify via `/summary`.
  * Cache resolved mappings inside `data/tickertape_mappings.json` to prevent repeated sitemap scraping and keep run times instantaneous (<1 sec).
  * Fetch current stock-level allocations from Tickertape.
  * Compute the pairwise minimum-weight intersection between portfolios.
  * Print a formatted ASCII Overlap Matrix Table and provide detailed holding-level analysis for high-overlap pairs (>10%).
* **Exclusions:** This tool does not alter any existing database files, and operates as an on-demand, read-only analytics script independent from the daily scheduled NAV job.
