# Proposal: Automated GitHub Pages Web Deployment

## 1. Objective
Deploy your interactive **`dashboard.html`** performance webpage as a live, secure, completely free web application hosted on **GitHub Pages**. This allows you to securely view and interact with your personal mutual fund dashboard directly from your iPhone, iPad, or any laptop, anywhere in the world, with zero hosting fees.

---

## 2. Background & Need
Currently, the interactive dashboard (`dashboard.html`) is compiled locally on your Mac or cached in GitHub Actions. To view it, you must manually open the file on your Mac.

By hosting it on GitHub Pages:
1. **Universal Access:** You can access your mutual fund metrics on the go (for example, checking active technical buy/sell alerts and consolidated allocations on your phone during market hours).
2. **Fully Automated Compilation:** Every morning at 10:30 AM IST, after fetching the latest NAVs and computing allocations, GitHub Actions will automatically rebuild the page and deploy the updated static website.
3. **Secure & Private:** The site is served directly from GitHub's globally-distributed, secure CDN.

---

## 3. Scope & Exclusions
* **Workflow Refactoring:** Update `.github/workflows/daily_nav.yml` to:
  * Grant necessary permissions (`pages: write`, `id-token: write`) to securely build and deploy to GitHub Pages.
  * Execute `portfolio_map_main.py` and `dashboard_main.py` during the daily run.
  * Reconstruct state caches (using `actions/cache`) so yesterday's NAVs and combined allocations are fully active.
  * Copy `dashboard.html` to `index.html` (the standard entry-point filename required by web servers).
  * Package and deploy the page securely to GitHub Pages using the official `actions/deploy-pages@v4` action.
* **Exclusions:** The deployed page is a completely static, client-side React-equivalent application. It operates securely on the browser and has no exposed database connections, ensuring total database safety.
