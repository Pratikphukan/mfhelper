# Proposal: Tactical "Profit-Taking & Trimming" Assistant

## 1. Objective
Introduce a dedicated **Tactical "Profit-Taking & Trimming" Assistant** inside your daily scheduled runs. This assistant complements your existing "Dip Buying" assistant by evaluating overbought confluence—when multiple independent technical indicators (RSI and 52W Peak proximity) align at extreme highs—and promoting them into a high-conviction profit-taking briefing card at the top of your email.

---

## 2. Background & Need
While buying dips is crucial, locking in profits during extreme bull runs (when greed is at an all-time high) is equally important to manage risk and maintain your target asset allocation. 

Currently, individual overbought signals (like RSI $\ge 70.0$) appear only as separate, raw rows in your bottom summary table. There is no automated confluence engine to identify when a fund has become mathematically overstretched on multiple metrics simultaneously, nor does the system provide high-conviction action recommendations (like trimming 5% or pausing SIPs) to protect your capital.

---

## 3. Scope & Exclusions
* **Overbought Confluence Logic:** Implement a 3-tier overbought confluence check in `mfhelper/alerts.py` to identify Tier-1 (Mild Momentum), Tier-2 (Moderate Overstretch), and Tier-3 (Extreme/Climax Peak) tactical trim signals.
* **Email Template Integration:** Update `dispatch_alerts_email` in `mfhelper/alerts.py` to display a separate, high-visibility **"Tactical Trim & Risk Reduction Briefing"** card (with red/gold warnings) at the top of the email body when overbought conditions are met.
* **Exclusions:** This is a read-only notification and analytical service. It will not execute trades or alter any shares automatically; all transactions remain manually operated by the user on Groww.
