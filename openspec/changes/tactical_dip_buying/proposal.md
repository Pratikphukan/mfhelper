# Proposal: Tactical "Dip Buying" Assistant in Email Alerts

## 1. Objective
Introduce a **Tactical "Dip Buying" Assistant** inside the daily HTML email alerts. This assistant evaluates **confluence**—when multiple independent technical indicators (RSI, 200D SMA, and 52W Peak Discount) trigger simultaneously—and promotes these high-conviction buying opportunities into a premium, prominent briefing card at the top of your email.

---

## 2. Background & Need
Currently, the daily NAV tracker checks and logs separate technical alerts individually. While useful, this places the cognitive burden on the investor to synthesize the separate metrics and decide whether a buy is justified.

By introducing confluence analysis, the system automatically distinguishes between:
1. **Isolated Noise:** A single indicator triggering (e.g., just a minor RSI pullback). These are kept in the standard alerts list.
2. **High-Conviction Dips:** Multiple independent indicators aligning on a single fund (e.g., heavily oversold *and* deeply discounted). These are highlighted with prioritized suggestions and immediate-action transaction links.

---

## 3. Scope & Exclusions
* **Fuzzy Confluence Logic:** Implement a 3-tier confluence filter in `mfhelper/alerts.py` to identify Tier-1 (Mild), Tier-2 (Moderate), and Tier-3 (Strong) tactical buy signals based on intersecting triggers.
* **Deep-Linked Transaction URLs:** Generate direct buy links pointing to Groww search results (using the fund's name) for immediate execution.
* **Email Template Refactoring:** Redesign the HTML email builder in `mfhelper/alerts.py` to conditionally render a beautiful, styled "Tactical Buy Briefing" section at the top of the email body when confluence conditions are met.
