# Tasks: Remote Cloud Trigger Button on Web Dashboard

This task checklist tracks the stages of implementing the remote cloud trigger button.

---

## 1. Task Breakdown

### Phase 1: Web UI & REST API Integration
* [ ] Add the **`🔄 Refresh Cloud Data`** button to the header of `dashboard_main.py`.
* [ ] Implement `triggerCloudRefresh()` in `dashboard_main.py` using `fetch()` to call GitHub's `/actions/workflows/daily_nav.yml/dispatches` endpoint.
* [ ] Store the access token securely in `localStorage` with prompt fallback and clearing on 401/403 errors.
* [ ] Display success and error feedback toasts.

### Phase 2: Compilation & Deploy
* [ ] Run `dashboard_main.py` locally to re-compile `dashboard.html`.
* [ ] Test the button locally in a browser.
* [ ] Commit, push, and watch the GitHub Actions workflow deploy to GitHub Pages (`https://pratikphookan.github.io/mfhelper/`).
