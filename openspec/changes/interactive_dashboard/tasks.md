# Tasks: Interactive Performance & Risk HTML Dashboard

This task checklist outlines the steps to build and verify the interactive HTML dashboard.

---

## 1. Task Breakdown

### Phase 1: Core Dashboard Script
* [ ] Create `dashboard_main.py` to recursively scan `data/fund_returns/` and read all fund JSONs.
* [ ] Parse and format trailing CAGRs, SIP XIRRs, volatility SDs, and risk ratios.
* [ ] Create a self-contained HTML template inside the python file with modern CSS and Chart.js setups.
* [ ] Write the aggregated data payload into the HTML template string and save it as `dashboard.html`.

### Phase 2: Web UI & Chart.js Implementation
* [ ] Style the dashboard using responsive Tailwind CSS.
* [ ] Build the **Efficient Frontier** (Risk vs Return) scatter plot.
* [ ] Build the **SIP XIRR** grouped bar chart.
* [ ] Build the **Risk-Adjusted Ratios** comparison bar chart.
* [ ] Add a clean **Summary Table** at the bottom of the webpage displaying all exact numerical statistics for quick reference.

### Phase 3: Final Verification
* [ ] Execute `dashboard_main.py` locally and verify that it produces `dashboard.html` without errors.
* [ ] Open `dashboard.html` in Safari/Chrome, verify that all charts render correctly, legends are interactive, and tooltips display exact percentages.
* [ ] Commit and push the final files to the remote repository.
