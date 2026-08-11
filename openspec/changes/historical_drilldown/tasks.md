# Tasks: Per-Fund Historical Drilldown Report

Here is the checklist of software engineering tasks executed to complete the historical drilldown report capability.

---

## 1. Task Breakdown

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
