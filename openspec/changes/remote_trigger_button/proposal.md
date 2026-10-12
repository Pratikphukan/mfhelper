# Proposal: Remote Cloud Trigger Button on Web Dashboard

## 1. Objective
Add a **"🔄 Trigger Cloud Refresh"** button directly to your live hosted GitHub Pages web dashboard (`https://pratikphukan.github.io/mfhelper/`). Clicking this button uses GitHub's official REST API to remotely trigger your `daily_nav.yml` workflow in the cloud, fetching fresh NAVs, calculating metrics, and re-deploying the live website in real-time.

---

## 2. Background & Need
Currently, to refresh the live GitHub Pages website outside the scheduled 10:30 AM IST window, you must open GitHub.com, navigate to the Actions tab, and manually trigger the workflow from the developer interface.

By adding a direct trigger button to your web dashboard:
1. **SaaS-like Web Control:** You can trigger a full cloud update directly from your web dashboard on your phone or laptop with a single click.
2. **Secure Token Authorization:** Uses GitHub's fine-grained Personal Access Token (PAT) stored locally in your browser's `localStorage` so unauthorized visitors cannot trigger cloud runs.
3. **Live Status Feedback:** Shows an animated loading toast informing you that GitHub Actions is actively building and deploying the fresh website in the background.

---

## 3. Scope & Exclusions
* **Web UI Button:** Add a prominent **`🔄 Refresh Cloud Data`** button in the header of `dashboard.html`.
* **GitHub REST API Integration:** Write JavaScript in `dashboard.html` to issue a `POST` request to `https://api.github.com/repos/Pratikphukan/mfhelper/actions/workflows/daily_nav.yml/dispatches`.
* **Token Prompting & Local Storage:** Prompt for a GitHub Access Token on first click and save it in `localStorage` for seamless single-click subsequent triggers.
* **Exclusions:** Does not require any external servers; operates purely client-side using GitHub's official REST API.
