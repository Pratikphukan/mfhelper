# OpenSpec: Per-Fund Historical Drilldown Report

This specification documents the on-demand, single-fund historical drilldown capability in **MFHelper**.

---

## 1. Objective
Extract the daily historical performance and technical indicators of a **single, specific mutual fund** over a fully configurable window of trailing trading days, and render the results vertically as a chronological timeline (newest first) in its own dedicated Google Sheet tab.

---

## 2. Design & Proposal

Unlike the daily scheduler (which appends a single wide-row across multiple funds) and the analytics tab (which condenses multiple funds into a single summary table), the historical drilldown provides a vertical daily log for **one fund at a time**.

```
                           [CLI Arguments]
                         --code & --days
                                │
                                ▼
                       [fetch_history]
                     Downloads NAV history
                      from api.mfapi.in
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│              compute_historical_rows() loop                      │
│                                                                 │
│   For date inside trailing N trading days:                      │
│     - NAV: raw value on date                                    │
│     - Day Change %: vs. (date - 1)                              │
│     - Dist from 52W High %: trailing 365 days from date         │
│     - Dist from 200D SMA %: trailing 200 trading days from date │
│     - RSI (14): smoothed Wilder RSI up to date                  │
└───────────────────────────────┬─────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│               HistoricalSheetWriter rendering                    │
│                                                                 │
│   - Creates a tab (e.g. "Nippon Small Cap 30D")                 │
│   - Writes Info Banner row (merged, italicized, blue background) │
│   - Writes Headers                                              │
│   - Formats columns natively (Date, Decimals, Percent, RSI)     │
└─────────────────────────────────────────────────────────────────┘
```

### Key Architectural Concerns:
1. **Lookback Windows:** Although the user only requests the last $N$ days of metrics to display (e.g. 30 days), each of those individual days requires looking back into the past (up to 365 days for the 52W High and 200 trading days for the SMA). Therefore, we must download and process the **entire historical NAV series** of the fund first, and then subset only the newest $N$ days for output rendering.
2. **Wilder Smoothing Seed:** RSI requires continuous smoothing from inception to have highly precise values. Thus, the calculation engine seeds its RSI calculations from the fund's absolute inception and walks forward to prevent point-to-point calculation discrepancies.

---

## 3. Command-Line Interface (CLI)

The CLI entry point `historical_main.py` supports fully configurable parameters:

```bash
.venv/bin/python historical_main.py --code <SCHEME_CODE> --days <DAYS> --tab <CUSTOM_TAB_NAME>
```

### Parameters:
* `--code` *(Required)*: The 6-digit AMFI scheme code (e.g. `147946` for Bandhan Small Cap).
* `--days` *(Optional, Default: 30)*: The number of historical trading days to compute and write. 
* `--tab` *(Optional)*: A custom name for the tab. If omitted, a clean title is dynamically derived from the fund name + the days count (e.g. `"Nippon Small Cap 60D"`).
* `--dry-run` *(Optional)*: Runs the calculations and formats the table in the console without writing to the Google Sheet.

---

## 4. Implementation Tasks

### Task 1: CLI Configuration & Entry Point
* [x] Design CLI arguments in `historical_main.py` using `argparse` to support configurable `--code`, `--days`, `--tab`, and `--dry-run`.
* [x] Incorporate logging to direct outputs to both console and `logs/mfhelper_historical.log`.

### Task 2: Subsetting and Lookback Computations
* [x] Implement `compute_historical_rows` in `mfhelper/historical.py`.
* [x] Correctly reference prior trading day's NAV across the subset boundaries to compute consistent `day_change_pct`.
* [x] Call and map historical helpers (`distance_from_52w_high`, `distance_from_200d_sma`, `rsi`) for each date in the requested window.

### Task 3: Sheet Template & Format Layout
* [x] Build `HistoricalSheetWriter` in `mfhelper/historical_sheet.py`.
* [x] Implement the `HistoricalSheetMeta` info banner styling (merged row, light blue background `#EBF2FF`, bold-italic font).
* [x] Implement strict column styling (Date format, 4-decimal format for NAV, percentage formatting with green/red trends, and 2-decimal RSI).
* [x] Add auto-resizing and Google API write retries.

### Task 4: Integration Verification
* [x] Run command using `--dry-run` to verify metrics accuracy.
* [x] Run with active sheet credentials to verify tab creation, resizing, formatting, and atomic cell updates.
