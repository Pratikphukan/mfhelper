# Tasks: Active vs. Benchmark Performance Auditor

This task checklist tracks the stages of implementing the Benchmark Auditor on the web dashboard.

---

## 1. Task Breakdown

### Phase 1: Dashboard UI Extensions
* [ ] Update `dashboard_main.py` to add a **`3Y Beat Rate`** column header to the main Statistics Grid table in `dashboard.html`.
* [ ] Add the 4th tab button **"Benchmark Audit"** to the slide-over fund explorer panel in `dashboard.html`.
* [ ] Implement the `formatBeatRateBadge` helper in client-side JavaScript.
* [ ] Implement the tab rendering logic for **"Benchmark Audit"** inside `switchTab()` to display 3Y/5Y beat rates, Information Ratios, and active excess returns.

### Phase 2: Local & Cloud Verification
* [ ] Run `returns_main.py` locally to refresh fund returns and attach `vs_benchmark` sections.
* [ ] Run `dashboard_main.py` locally to re-compile `dashboard.html`.
* [ ] Open `dashboard.html` in Safari/Chrome and verify that:
  * Equity funds display color-coded 🟢, 🟡, or 🔴 Beat Rate badges.
  * Non-equity/skipped funds display `n/a (Skipped)`.
  * Clicking on an equity fund slides open the panel with the complete **Benchmark Audit** tab!
* [ ] Stage, commit, and push all final changes to the remote repository.
* [ ] Trigger GitHub Actions to verify live deployment on GitHub Pages (`https://pratikphookan.github.io/mfhelper/`).
