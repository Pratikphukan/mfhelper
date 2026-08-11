# Tasks: Advanced Fund Analytics Upgrades

Here is the checklist of software engineering tasks executed to complete the analytics upgrade.

---

## 1. Task Breakdown

### Task 1: Scraper Extension
* [x] Modify `mfhelper/expense_ratio.py` -> `ExpenseRatioResult` to hold `aum_crore`.
* [x] Parse `aum` in crores from `__NEXT_DATA__` and round it to 2 decimal places.

### Task 2: Data Structure Refactoring
* [x] Update `AnalyticsRow` dataclass in `mfhelper/analytics_sheet.py` to support `sip_3y_pct`, `sip_5y_pct`, `calmar_3y`, and `max_dd_3y_pct`.
* [x] Extend the global `HEADERS` tuple and adjust `_COLUMN_FORMATS` mapping to align precisely.
* [x] Update `to_cells()` to serialize the new fields, replacing `None` with `""` for formatting.

### Task 3: Orchestrator Integration
* [x] Update `analytics_main.py` imports to include `hypothetical_sip_xirr`, `_drawdown_analysis`, and `risk_adjusted` from `mfhelper.returns_calc`.
* [x] Fetch the `as_of` date dynamically from the newest point in `result.history`.
* [x] Compute trailing 3-year history subset for Max Drawdown evaluation.
* [x] Populate the newly added fields inside the `AnalyticsRow` generation loop.

### Task 4: CLI & Integration Verification
* [x] Verify calculations run cleanly in dry-run mode.
* [x] Confirm that Google Sheet table creation, header styling, and column formats are atomic and error-free.
