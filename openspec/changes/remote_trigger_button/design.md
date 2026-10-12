# Design: Remote Cloud Trigger Button on Web Dashboard

## 1. System Topology & API Flow

When you click the button on your phone or computer, the browser communicates directly with GitHub's REST API:

```
┌────────────────────────────────────────────────────────┐
│            User clicks "🔄 Refresh Cloud Data"         │
│           (On https://pratikphukan.github.io)          │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼ (Check browser localStorage)
┌────────────────────────────────────────────────────────┐
│             Check GitHub Access Token                  │
│   - Token exists? Use it.                              │
│   - Token missing? Prompt user to paste token once.    │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼ (POST request via fetch API)
┌────────────────────────────────────────────────────────┐
│           GitHub Actions REST API Dispatch             │
│   POST https://api.github.com/repos/Pratikphukan/       │
│        mfhelper/actions/workflows/daily_nav.yml/       │
│        dispatches                                      │
│   Headers: Authorization: Bearer <TOKEN>               │
│   Body: { "ref": "main" }                              │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼ (HTTP 204 No Content Received)
┌────────────────────────────────────────────────────────┐
│             Toast Alert Notification                   │
│   "🚀 GitHub Cloud Runner Triggered!                   │
│    Fetching fresh NAVs and updating site..."           │
└────────────────────────────────────────────────────────┘
```

---

## 2. JavaScript REST API Integration (`dashboard_main.py` / `dashboard.html`)

Inside `dashboard.html`, we add the dispatch function:

```javascript
async function triggerCloudRefresh() {
    let token = localStorage.getItem('gh_pat_token');
    if (!token) {
        token = prompt("Enter your GitHub Personal Access Token (PAT) with 'actions:write' scope to trigger cloud runs:");
        if (!token) return;
        localStorage.setItem('gh_pat_token', token.trim());
    }

    try {
        const response = await fetch('https://api.github.com/repos/Pratikphukan/mfhelper/actions/workflows/daily_nav.yml/dispatches', {
            method: 'POST',
            headers: {
                'Accept': 'application/vnd.github+json',
                'Authorization': `Bearer ${token.trim()}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ ref: 'main' })
        });

        if (response.status === 204) {
            alert("🚀 Success! GitHub Cloud Runner has been triggered. Your website and sheet will be fully updated in 1-2 minutes!");
        } else if (response.status === 401 || response.status === 403) {
            alert("❌ Authorization failed! Your GitHub token may be invalid or missing 'actions:write' scope.");
            localStorage.removeItem('gh_pat_token');
        } else {
            alert(`⚠️ Error triggering cloud run (HTTP ${response.status}). Please check console.`);
        }
    } catch (err) {
        alert(`❌ Network error: ${err.message}`);
    }
}
```

---

## 3. UI Header Integration

We place the button right next to the **`🔍 View Portfolio Overlap Matrix`** button in the dashboard header:

```html
<button id="btn-cloud-refresh" onclick="triggerCloudRefresh()" class="bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-sm py-2.5 px-5 rounded-xl shadow-sm focus:outline-none transition-all flex items-center gap-2">
    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
    🔄 Refresh Cloud Data
</button>
```
