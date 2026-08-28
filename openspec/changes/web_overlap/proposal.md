# Proposal: Interactive Web-Based Portfolio Overlap Matrix

## 1. Objective
Introduce an **Interactive Web-Based Portfolio Overlap Matrix** directly inside your live hosted Web Dashboard (`dashboard.html`). This computes the pairwise stock holdings overlap percentages dynamically in the browser, rendering an interactive grid of your entire portfolio and a live stock-level inspector.

---

## 2. Background & Need
The `overlap_main.py` script generates an incredibly useful stock overlap matrix and writes it to Google Sheets and your terminal. While powerful, this layout is static. If you are on your phone or on the go, there is no way to click on a cell and instantly see which specific stocks are overlapping.

By integrating this into your hosted **GitHub Pages web-app**:
1. **Zero-Lag Interactive Matrix:** All calculations are performed instantaneously in your browser using optimized JavaScript.
2. **Interactive Stock Inspector:** Click on any cell in the matrix (for example, the intersection of JM Flexicap and Mirae Asset ELSS) to slide open a dedicated card listing the exact stock list and contribution weights driving that specific overlap!
3. **Heatmap Visualization:** Higher-overlap cells will automatically glow with soft red/amber warning colors, helping you audit portfolio redundancy in under 5 seconds.

---

## 3. Scope & Exclusions
* **Extended State Caching:** Update `portfolio_map_main.py` to cache individual fund-by-fund stock holdings inside `data/combined_portfolio_allocation.json` as a raw dictionary list.
* **Modern Matrix Web UI:** Build a responsive, beautiful full-screen modal in `dashboard.html` triggered by a **"🔍 View Portfolio Overlap Matrix"** button in your header.
* **Real-time JS Compiler:** Implement the mathematical minimum intersection algorithm ($\sum \min(W_A, W_B)$) in pure client-side JavaScript to compute pairwise values dynamically.
* **Live Sidebar Inspector:** Add a modal sub-panel to display stock-level overlaps when any cell in the matrix is clicked.
