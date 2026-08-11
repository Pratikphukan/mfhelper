# Proposal: Per-Fund Historical Drilldown Report

## 1. Objective
Extract the daily historical performance and technical indicators of a **single, specific mutual fund** over a fully configurable window of trailing trading days, and render the results vertically as a chronological timeline (newest first) in its own dedicated Google Sheet tab.

## 2. Background & Need
Where the daily NAV scheduler appends one row per *run* and the analytics report renders one row per *fund* (summary stats over multiple windows), there is no easy way to inspect a single fund's performance over its recent history.

The historical drilldown solves this by providing answers to questions like: *"Show me the last 30/60/90 days of NAV, day-change, 52-week highs, SMA, and RSI for fund X"* to evaluate a specific fund in high resolution.

## 3. Proposed Features

### A. Configurable Trailing Window
Make the trailing days window fully customizable (e.g. `--days 30`, `--days 60`, `--days 180`).

### B. Vertical Daily Log
Render the history as a vertical timeline:
1. **NAV:** Daily raw NAV.
2. **Day Change %:** Volatility relative to the prior NAV-publish day.
3. **Distance from 52-Week High %:** Visual indicator of proximity to 365-day peak.
4. **Distance from 200-Day SMA %:** Classical long-term trend indicator.
5. **RSI (14):** Daily Relative Strength Index with Wilder smoothing.

### C. Isolated Tabs
Each run automatically creates/overwrites its own dedicated tab named dynamically based on the fund name and days requested (e.g., `"Franklin US 60D"`) to keep the Google Sheet organized.
