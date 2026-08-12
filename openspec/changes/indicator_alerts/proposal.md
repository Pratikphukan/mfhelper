# Proposal: Technical Indicator "Buy/Sell Zone" Trigger Alerts

## 1. Objective
Introduce an automated, rule-based notification system that triggers real-time email alerts when any tracked mutual fund breaks critical technical indicators or structural levels. This removes emotional decision-making from investing and systematically alerts the investor to dip-buying or profit-taking zones.

---

## 2. Background & Need
While EOD mutual fund data is saved in Google Sheets daily, investors do not always open the sheet to check technical status. For high-volatility mutual funds (like Small-Cap or Sectoral funds), technical entry/exit zones can emerge and pass without notice.

By setting up an active alert engine, we can dynamically detect and flag:
1. **3-Tier RSI Buy Signals:**
   - **Tier 1 (Mild Pullback / Small Top-up):** RSI-14 drops below 55 (healthy cooling-off periods inside strong trends).
   - **Tier 2 (Moderate Dip / Moderate Lumpsum):** RSI-14 drops below 45 (medium corrections, ideal for standard accumulation).
   - **Tier 3 (Deep Oversold / Aggressive Lumpsum):** RSI-14 drops below 35 (extreme corrections, highly favorable entries).
2. **Overbought exit zones** (RSI-14 rising above 70).
3. **3-Tier 200D SMA Buy Signals:**
   - **Tier 1 (SMA Support / Small Top-up):** NAV is testing the 200-day Simple Moving Average (between +2% and -2%), acting as trend line support.
   - **Tier 2 (SMA Discount / Moderate Lumpsum):** NAV is trading in a moderate discount below SMA (between -2% and -10%).
   - **Tier 3 (SMA Capitulation / Aggressive Lumpsum):** NAV is in extreme capitulation below the 200-day average (<= -10%).
4. **200D SMA Trend Crossing Reversals:** Bullish breakouts above or bearish breakdowns below the long-term trend line.
5. **3-Tier 52W High Discount Signals (Peak Pyramiding):**
   - **Tier 1 (Mild Discount / Small Top-up):** NAV drops between -5% and -10% from its 52-week peak (common pullback within strong bull phases).
   - **Tier 2 (Moderate Discount / Moderate Lumpsum):** NAV drops between -10% and -20% from its 52-week peak (solid margin-of-safety corrections).
   - **Tier 3 (Deep Capitulation / Aggressive Lumpsum):** NAV drops $\le -20\%$ from its 52-week peak (rare generational buying opportunities or deep sector bottoms).

---

## 3. Scope & Exclusions
* **Configurable Thresholds:** Alert boundaries must be fully configurable in a separate YAML file (`config/alerts.yaml`).
* **Delivery Channel:** Built natively with **Email dispatch only** (utilizing standard SMTP configuration). Telegram and other external channel dependencies are out of scope.
* **Scheduling:** Built directly into the daily scheduler (`main.py`) to run immediately after EOD metrics are computed.
