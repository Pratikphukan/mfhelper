# Tasks: Gold ETF Analytics Tracker & Google Sheet Writer

This task checklist tracks the stages of implementing the Gold ETF Analytics feature.

---

## 1. Task Breakdown

### Phase 1: Configuration & Core Script
* [ ] Create `config/gold_etfs.yaml` listing the top 7 Indian Gold ETFs.
* [ ] Create `gold_etf_main.py` CLI script.
* [ ] Integrate history fetching from `mfapi.in` and risk/return computations from `mfhelper/returns_calc.py`.

### Phase 2: Google Sheets Synchronization
* [ ] Create `mfhelper/gold_etf_sheet.py` containing the Google Sheets tab writer.
* [ ] Connect to your Google Sheet, create/clear the **`Gold ETFs Analytics`** worksheet tab.
* [ ] Write the formatted ETF analytics table with percentage and ratio formatting.

### Phase 3: Verification & Deploy
* [ ] Execute `python gold_etf_main.py` locally and verify that it updates your Google Sheet cleanly.
* [ ] Commit and push the final working files to the remote repository.
