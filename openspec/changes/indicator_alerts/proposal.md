# Proposal: Technical Indicator "Buy/Sell Zone" Trigger Alerts

## 1. Objective
Introduce an automated, rule-based notification system that triggers real-time email alerts when any tracked mutual fund breaks critical technical indicators or structural levels. This removes emotional decision-making from investing and systematically alerts the investor to dip-buying or profit-taking zones.

---

## 2. Background & Need
While EOD mutual fund data is saved in Google Sheets daily, investors do not always open the sheet to check technical status. For high-volatility mutual funds (like Small-Cap or Sectoral funds), technical entry/exit zones can emerge and pass without notice.

By setting up an active alert engine, we can dynamically detect and flag:
1. **Oversold entry points** (RSI-14 dropping below 30).
2. **Overbought exit zones** (RSI-14 rising above 70).
3. **Long-term trend reversals** (the daily NAV crossing over or under its 200-day Simple Moving Average).
4. **Significant discounts** (NAV dropping more than 15% below its trailing 52-week peak).

---

## 3. Scope & Exclusions
* **Configurable Thresholds:** Alert boundaries must be fully configurable in a separate YAML file (`config/alerts.yaml`).
* **Delivery Channel:** Built natively with **Email dispatch only** (utilizing standard SMTP configuration). Telegram and other external channel dependencies are out of scope.
* **Scheduling:** Built directly into the daily scheduler (`main.py`) to run immediately after EOD metrics are computed.
