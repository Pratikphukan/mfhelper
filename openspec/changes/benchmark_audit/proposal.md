# Proposal: Active vs. Benchmark Performance Auditor

## 1. Objective
Introduce an **Active vs. Benchmark Performance Auditor** into the live Web Dashboard (`dashboard.html`). This calculates and displays the **Rolling 3Y Beat Rate %** and **Manager Information Ratio** for your active domestic equity funds, letting you evaluate if your active fund managers are consistently outperforming a passive index (like Nifty 500, Nifty Midcap 150) or if you are paying unnecessary expense ratio fees for underperformance.

---

## 2. Background & Need
Active mutual funds charge higher expense ratios than passive index funds. In a bull market, almost every fund displays positive returns, making it difficult to discern if a fund manager has genuine skill (generating Alpha) or is simply riding the broader market rally.

By evaluating the **Rolling 3Y Beat Rate %**:
1. **Mathematical Accuracy:** Compares fund CAGRs against benchmark CAGRs across all historical 3-year rolling windows rather than relying on a single point-in-time trailing return.
2. **Visual Badges:** Displays clear color-coded classification badges in the portfolio table:
   * **🟢 Elite Alpha ($\ge 70\%$ Beat Rate):** High manager skill. Outperforms the index consistently.
   * **🟡 Moderate Performer ($50\% - 69\%$ Beat Rate):** Average performance.
   * **🔴 Underperforming ($< 50\%$ Beat Rate):** Fund underperforms the index more than half the time.
3. **Explicit Scope:** Non-equity and international funds (Gold, Liquid, Arbitrage, International FoFs) are intentionally skipped as they do not benchmark against Indian equity indices.

---

## 3. Scope & Exclusions
* **Web Dashboard Table Integration:** Add a dedicated **`3Y Beat Rate %`** column to the main statistics grid in `dashboard.html`.
* **Slide-Over Panel Extension:** Add a **Tab 4: "Benchmark Audit"** inside the fund detail explorer modal, displaying:
  * Benchmark Index Name & Variant.
  * 3Y & 5Y Rolling Beat Rates.
  * 3Y & 5Y Information Ratios (skill per unit of active risk).
  * 3Y Active Excess Return CAGR %.
