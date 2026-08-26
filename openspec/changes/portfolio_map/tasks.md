# Tasks: Consolidated Portfolio Allocation Map

This task checklist tracks the stages of implementing the portfolio map and visual dashboard.

---

## 1. Task Breakdown

### Phase 1: Config & Core Math Engine
* [ ] Update `FundConfig` and `load_funds` inside `mfhelper/config.py` to support the optional `weight: float` field.
* [ ] Implement `portfolio_map_main.py` which:
  * Resolves funds, handles cache, and fetches Tickertape holdings.
  * Normalizes weights so they sum to exactly 100%.
  * Calculates consolidated stock exposures and aggregates them into sectors.
  * Prints a formatted terminal report of your Top 15 consolidated stocks and sector distributions.

### Phase 2: Google Sheets Synchronization
* [ ] Create `mfhelper/portfolio_map_sheet.py` containing the Google Sheets writer.
* [ ] Connect to your Google Sheet, create/clear a new **`Combined Allocation`** tab.
* [ ] Write the consolidated sector table and top 15 stocks table side-by-side.
* [ ] Style and format the sheet cells elegantly with percentage rendering.

### Phase 3: Web Dashboard Visualizations
* [ ] Save the consolidated stock and sector dataset inside `data/combined_portfolio_allocation.json` as a persistent cache.
* [ ] Update `dashboard_main.py` to read this cached file if it exists.
* [ ] Upgrade `dashboard.html` to display a beautiful, responsive top section containing:
  * An interactive **Combined Sector Distribution Donut Chart**.
  * An interactive **Combined Top Stock Holdings Progress Bar Chart**.

### Phase 4: Final Verification & Deploy
* [ ] Configure your personal investment weights inside `config/funds.yaml`.
* [ ] Execute `portfolio_map_main.py` and verify successful Sheet write and terminal output.
* [ ] Execute `dashboard_main.py` and verify gorgeous, responsive chart rendering inside your browser.
* [ ] Stage, commit, and push all final files to the remote repository.
