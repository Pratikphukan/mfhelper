# Design: Active vs. Benchmark Performance Auditor

## 1. Data Schema & Extraction Logic

The required metrics are already pre-calculated inside the `vs_benchmark` block of your fund JSON files (when `returns_main.py` is executed).

```json
"vs_benchmark": {
  "benchmark_name": "NIFTY MIDCAP 150",
  "variant": "PR",
  "beat_rate_pct": {
    "3y_window": 88.5,
    "5y_window": 92.1
  },
  "information_ratio_3y": 1.24,
  "information_ratio_5y": 1.45,
  "trailing_active_returns": {
    "3y_cagr_pct": 3.85
  }
}
```

In `dashboard_main.py` and `dashboard.html`, we read `fund.vs_benchmark` directly.

---

## 2. Classification & Badge Formatting Rules

Inside `dashboard.html`'s client-side JavaScript, we format the **3Y Beat Rate %** as follows:

```javascript
function formatBeatRateBadge(vs_bench) {
    if (!vs_bench || !vs_bench.beat_rate_pct || vs_bench.beat_rate_pct["3y_window"] === null) {
        return '<span class="text-slate-400 font-semibold">n/a (Skipped)</span>';
    }
    
    const rate = vs_bench.beat_rate_pct["3y_window"];
    if (rate >= 70.0) {
        return `<span class="bg-emerald-100 text-emerald-800 px-2.5 py-1 rounded-md font-extrabold text-xs">🟢 ${rate.toFixed(1)}%</span>`;
    } else if (rate >= 50.0) {
        return `<span class="bg-amber-100 text-amber-800 px-2.5 py-1 rounded-md font-extrabold text-xs">🟡 ${rate.toFixed(1)}%</span>`;
    } else {
        return `<span class="bg-rose-100 text-rose-800 px-2.5 py-1 rounded-md font-extrabold text-xs">🔴 ${rate.toFixed(1)}%</span>`;
    }
}
```

---

## 3. Slide-Over Panel "Benchmark Audit" Tab

When a fund row is clicked, a 4th tab **"Benchmark Audit"** is rendered:

* **Header:** Benchmark Index Name (e.g. `NIFTY MIDCAP 150`).
* **KPI Grid:**
  * **3Y Beat Rate:** `% of 3Y rolling windows beating index`.
  * **5Y Beat Rate:** `% of 5Y rolling windows beating index`.
  * **3Y Information Ratio:** Manager skill score (`Active Return / Tracking Error`).
  * **3Y Active Return:** Fund CAGR minus Index CAGR.
