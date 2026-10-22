# Tasks: Gold ETF Analytics Tracker & Google Sheet Writer

This task checklist tracks the stages of implementing the Gold ETF Analytics feature.

---

## 1. Task Breakdown

### Phase 1: Configuration & Core Script
* [x] Create `config/gold_etfs.yaml` listing the top 7 Indian Gold ETFs.
* [x] Create `gold_etf_main.py` CLI script.
* [x] Integrate history fetching from `mfapi.in` and risk/return computations from `mfhelper/returns_calc.py`.

### Phase 2: Google Sheets Synchronization
* [x] Create `mfhelper/gold_etf_sheet.py` containing the Google Sheets tab writer.
* [x] Connect to your Google Sheet, create/clear the **`Gold ETFs Analytics`** worksheet tab.
* [x] Write the formatted ETF analytics table with percentage and ratio formatting.

### Phase 3: Verification & Deploy
* [x] Execute `python gold_etf_main.py` locally and verify that it updates your Google Sheet cleanly.
* [x] Commit and push the final working files to the remote repository.
