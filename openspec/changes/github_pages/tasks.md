# Tasks: Automated GitHub Pages Web Deployment

This task checklist tracks the stages of implementing automated web-app deployment to GitHub Pages.

---

## 1. Task Breakdown

### Phase 1: Workflow Configuration
* [ ] Update `.github/workflows/daily_nav.yml` to:
  * Declare `permissions:` block at the top of the job.
  * Add `data/combined_portfolio_allocation.json` to the state cache path list so your combined portfolio map is successfully preserved across runs.
  * Append `python portfolio_map_main.py` and `python dashboard_main.py` steps after the daily tracker execution.
  * Add the server entry-point copy step: `cp dashboard.html index.html`.
  * Integrate `actions/configure-pages`, `actions/upload-pages-artifact`, and `actions/deploy-pages` deployment steps.

### Phase 2: GitHub Repository Setup (One-time only)
* [ ] Go to your repository on **GitHub.com** -> **Settings** -> **Pages**.
* [ ] Under **Build and deployment** -> **Source**, make sure it is set to **"GitHub Actions"** (this is the modern, secure way to deploy directly from your workflow run without creating separate branches!).

### Phase 3: Verification & Launch
* [ ] Commit and push the updated workflow file to the remote repository.
* [ ] Navigate to the repository's **Actions** tab, trigger **Daily NAV & Technical Alerts Scheduler** manually, and watch the live deployment logs!
* [ ] Once completed, copy and open your secure web URL:
  `https://pratikphukan.github.io/mfhelper/`
  on your phone or computer to explore your live mutual fund application!
