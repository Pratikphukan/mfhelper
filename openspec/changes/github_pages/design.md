# Design: Automated GitHub Pages Web Deployment

## 1. System Topology & Pipeline Flow

The GitHub Actions workflow coordinates fetching, calculation, and deployment inside a secure, containerized environment:

```
┌────────────────────────────────────────────────────────┐
│                   GitHub Actions Trigger               │
│               - Cron: 10:30 AM IST (TUE-SAT)           │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼ (Restore past NAV and Allocation states)
┌────────────────────────────────────────────────────────┐
│               State Cache Restoration                  │
│       - Restore: data/last_nav.json                    │
│       - Restore: data/sheet_columns.json               │
│       - Restore: data/combined_portfolio_allocation.json
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼ (Execute Python Engines)
┌────────────────────────────────────────────────────────┐
│               Run Portfolio Pipeline                   │
│   - python main.py (Daily NAVs, sheet & email alerts)  │
│   - python portfolio_map_main.py (Consolidated map)   │
│   - python dashboard_main.py (Compile web dashboard)   │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼ (Build Website Package)
┌────────────────────────────────────────────────────────┐
│               Prepare Pages Build                      │
│   - cp dashboard.html index.html (Map server entry-pt) │
│   - Save data caches back to GitHub Cache Database    │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼ (Deploy to GitHub Pages CDN)
┌────────────────────────────────────────────────────────┐
│              Deploys to Live Secure URL                │
│       - https://<username>.github.io/mfhelper/         │
└────────────────────────────────────────────────────────┘
```

---

## 2. GitHub Actions Permissions & Configuration

Modern GitHub Actions uses token-exchange security to deploy to GitHub Pages without hardcoded passwords or keys. We must define specific permissions inside `.github/workflows/daily_nav.yml`:

```yaml
permissions:
  contents: write    # Required to pull code & verify states
  pages: write       # Required to upload & trigger Pages deployment
  id-token: write    # Required to authenticate against GitHub's CDN
```

---

## 3. GitHub Pages Deployment Steps

Within the workflow, we use the official GitHub-supported Pages deployment actions:

```yaml
    # Prepare the website artifact
    - name: Copy dashboard to server index
      run: cp dashboard.html index.html

    - name: Setup Pages
      uses: actions/configure-pages@v5

    - name: Upload Pages Artifact
      uses: actions/upload-pages-artifact@v3
      with:
        path: '.' # Upload root folder containing index.html

    - name: Deploy to GitHub Pages
      id: deployment
      uses: actions/deploy-pages@v4
```
