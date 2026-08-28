# Tasks: Interactive Web-Based Portfolio Overlap Matrix

This task checklist tracks the development and deployment of the web overlap matrix.

---

## 1. Task Breakdown

### Phase 1: Cache Extension
* [x] Update `portfolio_map_main.py` to collect and cache `fund_holdings_dict` in `data/combined_portfolio_allocation.json`.

### Phase 2: Web Interface & Modal
* [ ] Add a **"🔍 View Portfolio Overlap Matrix"** button to the top header of `dashboard.html`.
* [ ] Build a beautiful full-screen modal in `dashboard.html` (`#overlap-modal-container`) styled with Tailwind CSS containing:
  * A scrollable **Heatmap Matrix Grid** table.
  * A **Stock Overlap Inspector** panel next to or below the grid.
* [ ] Write the Javascript bisection overlap engine inside the script.
* [ ] Dynamically draw the overlap grid rows and columns when the modal is opened.
* [ ] Set up the `click` trigger on grid cells: when clicked, render the detailed shared stocks table for those two funds showing individual stock allocations!

### Phase 3: Compilation & Cloud Deploy
* [ ] Execute `portfolio_map_main.py` and `dashboard_main.py` locally to compile the new `dashboard.html`.
* [ ] Verify the webpage in Safari/Chrome: test the modal, grid rendering, cells color highlights, and click triggers.
* [ ] Commit, push, and watch the GitHub Actions deploy-pages workflow execute perfectly to update your live website!
