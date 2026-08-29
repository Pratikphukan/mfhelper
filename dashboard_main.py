"""Interactive HTML Dashboard Generator for Mutual Fund Analytics.

Parses all processed JSON metrics inside ``data/fund_returns/`` and compiles
them into a self-contained, responsive ``dashboard.html`` webpage with
interactive charts and an ultra-premium slide-over exploration panel displaying
trailing, calendar-year, financial-year, and rolling returns.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
RETURNS_DIR = DATA_DIR / "fund_returns"
OUTPUT_FILE_PATH = PROJECT_ROOT / "dashboard.html"
LOGS_DIR = PROJECT_ROOT / "logs"


def _configure_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / "mfhelper_dashboard.log"
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    for handler in list(root.handlers):
        root.removeHandler(handler)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(fmt)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)


def main() -> int:
    _configure_logging()
    log = logging.getLogger("mfhelper.dashboard_main")
    log.info("=== MFHelper Interactive HTML Dashboard calculation starting ===")
    
    if not RETURNS_DIR.exists():
        log.error("Fund returns directory does not exist at: %s. Run returns_main.py first!", RETURNS_DIR)
        print("\n❌ Error: No fund returns database found! Please run 'returns_main.py' first to generate your performance data.")
        return 2

    json_files = list(RETURNS_DIR.glob("*.json"))
    if not json_files:
        log.error("No JSON files found inside: %s", RETURNS_DIR)
        print("\n❌ Error: No fund returns JSON files found! Please run 'returns_main.py' first to generate your performance data.")
        return 2

    # Load Combined Portfolio Allocation cache if it exists
    combined_allocation = None
    combined_cache_path = DATA_DIR / "combined_portfolio_allocation.json"
    if combined_cache_path.exists():
        try:
            with combined_cache_path.open("r", encoding="utf-8") as f:
                combined_allocation = json.load(f)
            log.info("Successfully loaded cached combined portfolio allocation.")
        except Exception as e:
            log.warning("Failed to load combined portfolio allocation cache: %s", e)

    # 1. Parse and Aggregate the fund datasets (Injecting full raw JSON structures!)
    aggregated_data = []
    
    for jf in json_files:
        try:
            with jf.open("r", encoding="utf-8") as f:
                fund_data = json.load(f)
            # Inject the entire fund data dict so the UI has access to all statistics
            aggregated_data.append(fund_data)
            log.info("Successfully loaded full data structure for: %s", fund_data.get("scheme_name"))
        except Exception as e:
            log.warning("Failed to parse fund returns file %s: %s", jf, e)

    if not aggregated_data:
        log.error("Failed to parse any valid fund returns JSON records.")
        return 2

    # Sort funds alphabetically by name for clean displays
    aggregated_data.sort(key=lambda x: x.get("scheme_name", ""))

    # 2. Build the beautiful self-contained HTML String
    html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MFHelper Mutual Fund Performance Dashboard</title>
    <!-- Tailwind CSS CDN -->
    <script src="https://cdn.tailwindcss.com"></script>
    <!-- Chart.js CDN -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
        body {{
            font-family: 'Plus Jakarta Sans', sans-serif;
            background-color: #f8fafc;
        }}
    </style>
</head>
<body class="text-slate-800 antialiased min-h-screen relative overflow-x-hidden">

    <div class="max-w-[1400px] mx-auto p-4 md:p-8">
        
        <!-- Header -->
        <header class="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200 pb-6 mb-8">
            <div>
                <h1 class="text-3xl font-extrabold text-slate-900 tracking-tight">📈 MFHelper Portfolio Dashboard</h1>
                <p class="text-slate-500 mt-1 text-sm pr-4">Interactive performance & risk metrics analyzer. Click any row in the table below to explore, or view your overall portfolio overlap matrix.</p>
                <div class="mt-4 flex gap-4">
                    <button id="btn-open-overlap" onclick="openOverlapModal()" class="bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-sm py-2.5 px-5 rounded-xl shadow-sm focus:outline-none transition-all flex items-center gap-2">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
                        🔍 View Portfolio Overlap Matrix
                    </button>
                </div>
            </div>
            <div class="bg-white border border-slate-200 px-4 py-3 rounded-xl shadow-sm text-right">
                <div class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Last updated (IST)</div>
                <div class="text-sm font-bold text-slate-700 mt-0.5">{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
            </div>
        </header>

        <!-- Combined Portfolio Map Section -->
        <section id="combined-allocation-section" class="hidden mb-8">
            <div class="bg-white border border-slate-200 p-6 rounded-2xl shadow-sm">
                <div class="border-b border-slate-100 pb-4 mb-6 flex justify-between items-center flex-wrap gap-4">
                    <div>
                        <h2 class="text-xl font-extrabold text-slate-900 tracking-tight">🧱 True Consolidated Asset Allocation Map</h2>
                        <p class="text-xs text-slate-400 font-semibold mt-0.5">Aggregates your fund portfolios using custom investment weights to show your true consolidated concentrations.</p>
                    </div>
                    <span id="allocation-cache-date" class="text-xs font-bold text-slate-400 bg-slate-100 px-3 py-1.5 rounded-lg">Updated: -</span>
                </div>
                <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">
                    <!-- Sector Donut Chart -->
                    <div class="lg:col-span-4 flex flex-col justify-center border-r border-slate-100 pr-6">
                        <h3 class="text-sm font-bold text-slate-400 uppercase tracking-wider mb-4 text-center lg:text-left">Combined Asset Class Distribution</h3>
                        <div class="relative h-[240px] w-full flex items-center justify-center">
                            <canvas id="chart-combined-sectors"></canvas>
                        </div>
                    </div>
                    <!-- Top Stocks Progress Bars -->
                    <div class="lg:col-span-8 flex flex-col justify-between">
                        <h3 class="text-sm font-bold text-slate-400 uppercase tracking-wider mb-4">Top 6 Consolidated Stock Holdings</h3>
                        <div class="space-y-4" id="combined-stocks-list">
                            <!-- Dynamically populated progress bars -->
                        </div>
                    </div>
                </div>
            </div>
        </section>

        <!-- Inactive Combined Map Banner -->
        <section id="combined-allocation-banner" class="mb-8">
            <div class="bg-slate-50 border-2 border-dashed border-slate-200 p-6 rounded-2xl text-center">
                <h3 class="text-lg font-bold text-slate-700">🧱 True Consolidated Asset Allocation Map is inactive</h3>
                <p class="text-sm text-slate-400 font-semibold mt-1">To unlock interactive combined sector donuts and top stocks progress bars across all 12 funds combined, run the portfolio map script locally on your Mac:</p>
                <div class="mt-4">
                    <code class="bg-slate-200/60 px-4 py-2 rounded-xl text-slate-700 font-bold text-xs">.venv/bin/python portfolio_map_main.py</code>
                </div>
            </div>
        </section>

        <!-- KPI Cards Grid -->
        <section class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <!-- Card 1 -->
            <div class="bg-white border border-slate-200 p-5 rounded-2xl shadow-sm flex flex-col justify-between">
                <span class="text-xs font-bold text-slate-400 uppercase tracking-wider">Top 3Y CAGR Return</span>
                <div class="mt-2">
                    <span class="text-2xl font-black text-emerald-600" id="kpi-top-cagr">n/a</span>
                    <p class="text-xs text-slate-500 font-semibold mt-1 truncate" id="kpi-top-cagr-name">-</p>
                </div>
            </div>
            <!-- Card 2 -->
            <div class="bg-white border border-slate-200 p-5 rounded-2xl shadow-sm flex flex-col justify-between">
                <span class="text-xs font-bold text-slate-400 uppercase tracking-wider">Highest 3Y SIP XIRR</span>
                <div class="mt-2">
                    <span class="text-2xl font-black text-indigo-600" id="kpi-top-sip">n/a</span>
                    <p class="text-xs text-slate-500 font-semibold mt-1 truncate" id="kpi-top-sip-name">-</p>
                </div>
            </div>
            <!-- Card 3 -->
            <div class="bg-white border border-slate-200 p-5 rounded-2xl shadow-sm flex flex-col justify-between">
                <span class="text-xs font-bold text-slate-400 uppercase tracking-wider">Best Sharpe Ratio (3Y)</span>
                <div class="mt-2">
                    <span class="text-2xl font-black text-amber-600" id="kpi-top-sharpe">n/a</span>
                    <p class="text-xs text-slate-500 font-semibold mt-1 truncate" id="kpi-top-sharpe-name">-</p>
                </div>
            </div>
            <!-- Card 4 -->
            <div class="bg-white border border-slate-200 p-5 rounded-2xl shadow-sm flex flex-col justify-between">
                <span class="text-xs font-bold text-slate-400 uppercase tracking-wider">Lowest Volatility (3Y SD)</span>
                <div class="mt-2">
                    <span class="text-2xl font-black text-cyan-600" id="kpi-lowest-sd">n/a</span>
                    <p class="text-xs text-slate-500 font-semibold mt-1 truncate" id="kpi-lowest-sd-name">-</p>
                </div>
            </div>
        </section>

        <!-- Charts Grid Layout -->
        <main class="grid grid-cols-1 lg:grid-cols-12 gap-6 mb-8">
            <!-- Left Side: Scatter Plot (The Efficient Frontier) -->
            <div class="bg-white border border-slate-200 p-6 rounded-2xl shadow-sm lg:col-span-7 flex flex-col">
                <div class="mb-4">
                    <h3 class="text-lg font-bold text-slate-900">🎯 The Efficient Frontier</h3>
                    <p class="text-xs text-slate-400 font-semibold mt-0.5">Visualizes Volatility (Risk) on X-axis vs. 3Y CAGR (Return) on Y-axis. Top-left is optimal.</p>
                </div>
                <div class="relative h-[400px] w-full flex-grow flex items-center justify-center">
                    <canvas id="chart-frontier"></canvas>
                </div>
            </div>

            <!-- Right Side: Risk Ratios -->
            <div class="bg-white border border-slate-200 p-6 rounded-2xl shadow-sm lg:col-span-5 flex flex-col">
                <div class="mb-4">
                    <h3 class="text-lg font-bold text-slate-900">🛡️ Risk-Adjusted Quality Scores</h3>
                    <p class="text-xs text-slate-400 font-semibold mt-0.5">Compares Sharpe, Sortino, and Calmar ratios. Higher scores signify better risk-adjusted return efficiency.</p>
                </div>
                <div class="relative h-[400px] w-full flex-grow flex items-center justify-center">
                    <canvas id="chart-ratios"></canvas>
                </div>
            </div>

            <!-- Full Width: SIP XIRR Grouped Bar Chart -->
            <div class="bg-white border border-slate-200 p-6 rounded-2xl shadow-sm lg:col-span-12">
                <div class="mb-4">
                    <h3 class="text-lg font-bold text-slate-900">🛒 SIP Performance Comparison</h3>
                    <p class="text-xs text-slate-400 font-semibold mt-0.5">Compares the true annualized rate of return (XIRR) of a monthly ₹10,000 SIP across 3Y, 5Y, and 10Y horizons.</p>
                </div>
                <div class="relative h-[380px] w-full">
                    <canvas id="chart-sip"></canvas>
                </div>
            </div>
        </main>

        <!-- Tabular Grid View -->
        <section class="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden mb-8">
            <div class="px-6 py-5 border-b border-slate-200 bg-slate-50/50">
                <h3 class="text-lg font-bold text-slate-900">📋 Complete Portfolio Statistics Grid</h3>
                <p class="text-xs text-slate-400 font-semibold mt-0.5">Click on any fund row below to slide open a comprehensive year-by-year and rolling returns audit panel!</p>
            </div>
            <div class="overflow-x-auto">
                <table class="w-full text-left border-collapse text-sm">
                    <thead>
                        <tr class="bg-slate-100 text-slate-500 uppercase text-xs font-bold tracking-wider border-b border-slate-200">
                            <th class="py-3.5 px-4 font-extrabold text-slate-600">Fund Name / Code</th>
                            <th class="py-3.5 px-4 text-center font-extrabold text-slate-600">1Y Abs</th>
                            <th class="py-3.5 px-4 text-center font-extrabold text-slate-600">3Y CAGR</th>
                            <th class="py-3.5 px-4 text-center font-extrabold text-slate-600">5Y CAGR</th>
                            <th class="py-3.5 px-4 text-center font-extrabold text-slate-600">3Y SIP XIRR</th>
                            <th class="py-3.5 px-4 text-center font-extrabold text-slate-600">5Y SIP XIRR</th>
                            <th class="py-3.5 px-4 text-center font-extrabold text-slate-600">Ann. SD (3Y)</th>
                            <th class="py-3.5 px-4 text-center font-extrabold text-slate-600">Sharpe (3Y)</th>
                            <th class="py-3.5 px-4 text-center font-extrabold text-slate-600">Sortino (3Y)</th>
                            <th class="py-3.5 px-4 text-center font-extrabold text-slate-600">Calmar (3Y)</th>
                        </tr>
                    </thead>
                    <tbody id="stats-table-body" class="divide-y divide-slate-100 text-slate-700 font-medium cursor-pointer">
                        <!-- Javascript will dynamically build row content here -->
                    </tbody>
                </table>
            </div>
        </section>

    </div>

    <!-- Premium Slide-over Side Panel -->
    <div id="modal-container" class="fixed inset-0 bg-slate-950/40 backdrop-blur-sm z-50 flex justify-end opacity-0 pointer-events-none transition-opacity duration-300">
        <div id="modal-panel" class="w-full max-w-2xl bg-white h-screen shadow-2xl flex flex-col translate-x-full transition-transform duration-300 ease-out border-l border-slate-200">
            <!-- Modal Header -->
            <div class="p-6 border-b border-slate-200 flex justify-between items-start bg-slate-50">
                <div>
                    <h3 id="modal-fund-name" class="text-xl font-bold text-slate-900 leading-tight pr-4">Fund Details</h3>
                    <span id="modal-fund-code" class="text-xs font-bold text-slate-400 mt-1 block uppercase tracking-wider">AMFI: -</span>
                </div>
                <button onclick="closeModal()" class="text-slate-400 hover:text-slate-600 hover:bg-slate-200/50 p-2 rounded-lg focus:outline-none transition-all">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                </button>
            </div>
            <!-- Modal Tabs -->
            <div class="px-6 border-b border-slate-200 flex gap-6 text-sm font-bold text-slate-400 bg-slate-50/50">
                <button id="tab-btn-trailing" onclick="switchTab('trailing')" class="py-4 border-b-2 border-emerald-600 text-emerald-600 focus:outline-none transition-all">Trailing & Extremes</button>
                <button id="tab-btn-yearly" onclick="switchTab('yearly')" class="py-4 border-b-2 border-transparent hover:text-slate-600 focus:outline-none transition-all">Yearly Returns</button>
                <button id="tab-btn-rolling" onclick="switchTab('rolling')" class="py-4 border-b-2 border-transparent hover:text-slate-600 focus:outline-none transition-all">Rolling Analysis</button>
            </div>
            <!-- Modal Content -->
            <div class="flex-grow p-6 overflow-y-auto bg-white" id="modal-content">
                <!-- Dynamically populated tab content -->
            </div>
        </div>
    </div>

    <!-- Overlap Matrix Modal -->
    <div id="overlap-modal-container" class="fixed inset-0 bg-slate-950/40 backdrop-blur-sm z-50 flex justify-center items-center opacity-0 pointer-events-none transition-opacity duration-300">
        <div id="overlap-modal-panel" class="w-full max-w-6xl bg-white h-[90vh] rounded-2xl shadow-2xl flex flex-col translate-y-12 transition-transform duration-300 ease-out border border-slate-200 overflow-hidden">
            <!-- Header -->
            <div class="p-6 border-b border-slate-200 flex justify-between items-center bg-slate-50">
                <div>
                    <h3 class="text-xl font-bold text-slate-900 leading-tight">🔍 Mutual Fund Portfolio Overlap Analyzer</h3>
                    <p class="text-xs text-slate-400 font-bold mt-1 uppercase tracking-wider">Computes stock-level intersections. Click on any cell in the grid to see the exact shared stocks!</p>
                </div>
                <button onclick="closeOverlapModal()" class="text-slate-400 hover:text-slate-600 hover:bg-slate-200/50 p-2 rounded-lg focus:outline-none transition-all">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                </button>
            </div>
            <!-- Body -->
            <div class="flex-grow flex flex-col lg:flex-row overflow-hidden">
                <!-- Left: Scrollable Matrix Grid -->
                <div class="lg:w-7/12 p-6 overflow-auto border-r border-slate-100 bg-white">
                    <div class="min-w-[600px]" id="overlap-matrix-container">
                        <!-- Javascript will dynamically build matrix grid -->
                    </div>
                </div>
                <!-- Right: Overlap Details Panel -->
                <div class="lg:w-5/12 p-6 flex flex-col bg-slate-50 overflow-y-auto">
                    <h4 class="text-xs font-black uppercase text-slate-400 tracking-wider mb-4" id="overlap-details-title">Select a cell in the matrix to view stock-level details</h4>
                    <div class="space-y-4 flex-grow" id="overlap-details-body">
                        <div class="text-slate-400 text-center py-12 font-medium">Click on any colored cell in the matrix grid (e.g. intersecting Axis and SBI) to instantly reveal their shared stocks and allocation weights here.</div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Data Injection -->
    <script id="portfolio-data" type="application/json">
        {json.dumps(aggregated_data)}
    </script>
    <script id="combined-allocation-data" type="application/json">
        {json.dumps(combined_allocation)}
    </script>

    <script>
        const dataset = JSON.parse(document.getElementById('portfolio-data').textContent);
        console.log("Loaded full dataset records:", dataset.length);

        // --- Populate Combined Allocation Map if Active ---
        const combinedRaw = document.getElementById('combined-allocation-data').textContent;
        const combined = combinedRaw && combinedRaw !== "null" ? JSON.parse(combinedRaw) : null;
        
        if (combined) {{
            document.getElementById('combined-allocation-banner').classList.add('hidden');
            document.getElementById('combined-allocation-section').classList.remove('hidden');
            document.getElementById('allocation-cache-date').textContent = `Updated: ${{combined.last_updated}}`;
            
            // Build Stock Progress Bars
            const stockContainer = document.getElementById('combined-stocks-list');
            stockContainer.innerHTML = '';
            
            combined.stocks.slice(0, 6).forEach(st => {{
                const stockDiv = document.createElement('div');
                stockDiv.className = 'flex flex-col gap-1.5';
                
                // Normalizing the visual bar width based on highest stock weight
                const maxPct = combined.stocks[0].weight || 100.0;
                const progressWidth = (st.weight / maxPct) * 100.0;
                
                stockDiv.innerHTML = `
                    <div class="flex justify-between text-xs font-bold text-slate-700">
                        <span>${{st.name}}</span>
                        <span>${{st.weight.toFixed(2)}}%</span>
                    </div>
                    <div class="w-full h-3 bg-slate-100 rounded-full overflow-hidden">
                        <div class="h-full bg-emerald-500 rounded-full" style="width: ${{progressWidth}}%"></div>
                    </div>
                `;
                stockContainer.appendChild(stockDiv);
            }});
            
            // Build Sector Donut Chart
            const sectorLabels = combined.sectors.map(s => s.name);
            const sectorWeights = combined.sectors.map(s => s.weight);
            
            new Chart(document.getElementById('chart-combined-sectors'), {{
                type: 'doughnut',
                data: {{
                    labels: sectorLabels,
                    datasets: [{{
                        data: sectorWeights,
                        backgroundColor: ['#10b981', '#3b82f6', '#8b5cf6', '#f59e0b', '#ec4899', '#06b6d4', '#64748b'],
                        borderWidth: 2,
                        borderColor: '#ffffff'
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{ position: 'right', labels: {{ boxWidth: 10, font: {{ weight: 'bold', size: 10 }} }} }},
                        tooltip: {{
                            callbacks: {{
                                label: function(ctx) {{
                                    return ` ${{ctx.label}}: ${{ctx.raw.toFixed(2)}}%`;
                                }}
                            }}
                        }}
                    }}
                }}
            }});
        }}

        // --- Helper formatting ---
        const fmtPct = (val) => (val !== null && val !== undefined) ? `${{val.toFixed(2)}}%` : 'n/a';
        const fmtNum = (val) => (val !== null && val !== undefined) ? val.toFixed(2) : 'n/a';

        // --- Populate KPIs ---
        let topCagr = -Infinity, topCagrName = '-';
        let topSip = -Infinity, topSipName = '-';
        let topSharpe = -Infinity, topSharpeName = '-';
        let lowestSd = Infinity, lowestSdName = '-';

        dataset.forEach(fund => {{
            const tr = fund.trailing_returns || {{}};
            const sip = fund.hypothetical_sip_xirr || {{}};
            const risk = fund.risk || {{}};
            const ra = fund.risk_adjusted || {{}};

            const cagr_3y = tr["3y_cagr_pct"];
            const sip_3y = sip["3y_xirr_pct"];
            const sharpe_3y = ra["sharpe_3y"];
            const sd_3y = risk["sd_3y_annualized_pct"];

            if (cagr_3y && cagr_3y > topCagr) {{
                topCagr = cagr_3y; topCagrName = fund.scheme_name;
            }}
            if (sip_3y && sip_3y > topSip) {{
                topSip = sip_3y; topSipName = fund.scheme_name;
            }}
            if (ra.sharpe_3y && ra.sharpe_3y > topSharpe) {{
                topSharpe = ra.sharpe_3y; topSharpeName = fund.scheme_name;
            }}
            if (sd_3y && sd_3y < lowestSd) {{
                lowestSd = sd_3y; lowestSdName = fund.scheme_name;
            }}
        }});

        if (topCagr !== -Infinity) {{
            document.getElementById('kpi-top-cagr').textContent = fmtPct(topCagr);
            document.getElementById('kpi-top-cagr-name').textContent = topCagrName;
        }}
        if (topSip !== -Infinity) {{
            document.getElementById('kpi-top-sip').textContent = fmtPct(topSip);
            document.getElementById('kpi-top-sip-name').textContent = topSipName;
        }}
        if (topSharpe !== -Infinity) {{
            document.getElementById('kpi-top-sharpe').textContent = fmtNum(topSharpe);
            document.getElementById('kpi-top-sharpe-name').textContent = topSharpeName;
        }}
        if (lowestSd !== Infinity) {{
            document.getElementById('kpi-lowest-sd').textContent = fmtPct(lowestSd);
            document.getElementById('kpi-lowest-sd-name').textContent = lowestSdName;
        }}

        // --- Populate Table ---
        const tbody = document.getElementById('stats-table-body');
        dataset.forEach((fund, index) => {{
            const tr = fund.trailing_returns || {{}};
            const sip = fund.hypothetical_sip_xirr || {{}};
            const risk = fund.risk || {{}};
            const ra = fund.risk_adjusted || {{}};

            const rowElement = document.createElement('tr');
            rowElement.className = 'hover:bg-slate-50/50 transition-colors border-b border-slate-100';
            rowElement.onclick = () => openModal(index);
            rowElement.innerHTML = `
                <td class="py-3 px-4 font-bold text-slate-800">
                    <div class="truncate max-w-[320px]">${{fund.scheme_name}}</div>
                    <span class="text-xs text-slate-400 font-bold uppercase">AMFI: ${{fund.scheme_code}}</span>
                </td>
                <td class="py-3 px-4 text-center text-slate-600">${{fmtPct(tr["1y_absolute_pct"])}}</td>
                <td class="py-3 px-4 text-center font-bold text-slate-900">${{fmtPct(tr["3y_cagr_pct"])}}</td>
                <td class="py-3 px-4 text-center text-slate-600">${{fmtPct(tr["5y_cagr_pct"])}}</td>
                <td class="py-3 px-4 text-center text-slate-600">${{fmtPct(sip["3y_xirr_pct"])}}</td>
                <td class="py-3 px-4 text-center text-slate-600">${{fmtPct(sip["5y_xirr_pct"])}}</td>
                <td class="py-3 px-4 text-center text-slate-600">${{fmtPct(risk["sd_3y_annualized_pct"])}}</td>
                <td class="py-3 px-4 text-center font-bold text-amber-700">${{fmtNum(ra["sharpe_3y"])}}</td>
                <td class="py-3 px-4 text-center text-slate-600">${{fmtNum(ra["sortino_3y"])}}</td>
                <td class="py-3 px-4 text-center text-slate-600">${{fmtNum(ra["calmar_3y"])}}</td>
            `;
            tbody.appendChild(rowElement);
        }});

        // --- CHART 1: Efficient Frontier (Scatter Plot) ---
        const scatterData = dataset
            .filter(f => f.risk?.["sd_3y_annualized_pct"] !== undefined && f.trailing_returns?.["3y_cagr_pct"] !== undefined)
            .map(f => ({{
                x: f.risk["sd_3y_annualized_pct"],
                y: f.trailing_returns["3y_cagr_pct"],
                label: f.scheme_name
            }}));

        new Chart(document.getElementById('chart-frontier'), {{
            type: 'scatter',
            data: {{
                datasets: [{{
                    label: 'Mutual Funds',
                    data: scatterData,
                    backgroundColor: '#10b981',
                    hoverBackgroundColor: '#047857',
                    pointRadius: 8,
                    pointHoverRadius: 11
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                scales: {{
                    x: {{
                        title: {{ display: true, text: 'Volatility: Standard Deviation (3Y) %', font: {{ weight: 'bold' }} }},
                        grid: {{ color: '#f1f5f9' }}
                    }},
                    y: {{
                        title: {{ display: true, text: 'Return: Trailing CAGR (3Y) %', font: {{ weight: 'bold' }} }},
                        grid: {{ color: '#f1f5f9' }}
                    }}
                }},
                plugins: {{
                    legend: {{ display: false }},
                    tooltip: {{
                        callbacks: {{
                            label: function(ctx) {{
                                return `${{ctx.raw.label}}: Volatility: ${{ctx.raw.x.toFixed(2)}}%, Return: ${{ctx.raw.y.toFixed(2)}}%`;
                            }}
                        }}
                    }}
                }}
            }}
        }});

        // --- CHART 2: Risk-Adjusted Quality Scores ---
        const ratioLabels = dataset.map(f => f.scheme_name.substring(0, 15) + '...');
        const sharpeSeries = dataset.map(f => f.risk_adjusted?.["sharpe_3y"]);
        const sortinoSeries = dataset.map(f => f.risk_adjusted?.["sortino_3y"]);
        const calmarSeries = dataset.map(f => f.risk_adjusted?.["calmar_3y"]);

        new Chart(document.getElementById('chart-ratios'), {{
            type: 'bar',
            data: {{
                labels: ratioLabels,
                datasets: [
                    {{ label: 'Sharpe', data: sharpeSeries, backgroundColor: '#f59e0b' }},
                    {{ label: 'Sortino', data: sortinoSeries, backgroundColor: '#3b82f6' }},
                    {{ label: 'Calmar', data: calmarSeries, backgroundColor: '#8b5cf6' }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                scales: {{
                    x: {{ grid: {{ display: false }} }},
                    y: {{ title: {{ display: true, text: 'Score Value' }}, grid: {{ color: '#f1f5f9' }} }}
                }},
                plugins: {{
                    legend: {{ position: 'bottom', labels: {{ boxWidth: 12, font: {{ weight: 'semibold' }} }} }}
                }}
            }}
        }});

        // --- CHART 3: SIP Performance ---
        const sipLabels = dataset.map(f => f.scheme_name.substring(0, 20) + '...');
        const sip3ySeries = dataset.map(f => f.hypothetical_sip_xirr?.["3y_xirr_pct"]);
        const sip5ySeries = dataset.map(f => f.hypothetical_sip_xirr?.["5y_xirr_pct"]);
        const sip10ySeries = dataset.map(f => f.hypothetical_sip_xirr?.["10y_xirr_pct"]);

        new Chart(document.getElementById('chart-sip'), {{
            type: 'bar',
            data: {{
                labels: sipLabels,
                datasets: [
                    {{ label: '3Y SIP XIRR', data: sip3ySeries, backgroundColor: '#4f46e5' }},
                    {{ label: '5Y SIP XIRR', data: sip5ySeries, backgroundColor: '#6366f1' }},
                    {{ label: '10Y SIP XIRR', data: sip10ySeries, backgroundColor: '#a5b4fc' }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                scales: {{
                    x: {{ grid: {{ display: false }} }},
                    y: {{
                        title: {{ display: true, text: 'Annualized Return (XIRR) %', font: {{ weight: 'bold' }} }},
                        grid: {{ color: '#f1f5f9' }},
                        ticks: {{ callback: function(value) {{ return value + '%'; }} }}
                    }}
                }},
                plugins: {{
                    legend: {{ position: 'bottom', labels: {{ boxWidth: 12, font: {{ weight: 'semibold' }} }} }}
                }}
            }}
        }});

        // --- SLIDE-OVER EXPLORATION MODAL LOGIC ---
        let selectedFundIndex = null;
        let activeTab = 'trailing';

        function openModal(index) {{
            selectedFundIndex = index;
            const fund = dataset[index];
            
            document.getElementById('modal-fund-name').textContent = fund.scheme_name;
            document.getElementById('modal-fund-code').textContent = `AMFI: ${{fund.scheme_code}} | Data Source: ${{fund.data_source}}`;
            
            // Show Container with fade and Slide Panel with translate
            const container = document.getElementById('modal-container');
            const panel = document.getElementById('modal-panel');
            
            container.classList.remove('opacity-0', 'pointer-events-none');
            panel.classList.remove('translate-x-full');
            
            // Render default tab
            switchTab('trailing');
        }}

        function closeModal() {{
            const container = document.getElementById('modal-container');
            const panel = document.getElementById('modal-panel');
            
            container.classList.add('opacity-0', 'pointer-events-none');
            panel.classList.add('translate-x-full');
        }}

        // Close on background click
        document.getElementById('modal-container').onclick = function(e) {{
            if (e.target === this) closeModal();
        }};

        function switchTab(tabName) {{
            activeTab = tabName;
            
            // Update tab button styles
            const tabs = ['trailing', 'yearly', 'rolling'];
            tabs.forEach(t => {{
                const btn = document.getElementById(`tab-btn-${{t}}`);
                if (t === tabName) {{
                    btn.className = "py-4 border-b-2 border-emerald-600 text-emerald-600 focus:outline-none font-extrabold";
                }} else {{
                    btn.className = "py-4 border-b-2 border-transparent text-slate-400 hover:text-slate-600 focus:outline-none";
                }}
            }});
            
            const fund = dataset[selectedFundIndex];
            const contentDiv = document.getElementById('modal-content');
            
            if (tabName === 'trailing') {{
                const tr = fund.trailing_returns || {{}};
                const ex = fund.extremes || {{}};
                contentDiv.innerHTML = `
                    <div class="space-y-6">
                        <div>
                            <h4 class="text-sm font-bold uppercase text-slate-400 tracking-wider mb-3">Trailing Returns Summary</h4>
                            <div class="grid grid-cols-2 gap-4">
                                <div class="bg-slate-50 p-4 rounded-xl border border-slate-100"><div class="text-xs text-slate-400 font-semibold">1-Week return</div><div class="text-lg font-bold mt-1 text-slate-800">${{fmtPct(tr["1w_pct"])}}</div></div>
                                <div class="bg-slate-50 p-4 rounded-xl border border-slate-100"><div class="text-xs text-slate-400 font-semibold">1-Month return</div><div class="text-lg font-bold mt-1 text-slate-800">${{fmtPct(tr["1m_pct"])}}</div></div>
                                <div class="bg-slate-50 p-4 rounded-xl border border-slate-100"><div class="text-xs text-slate-400 font-semibold">3-Month return</div><div class="text-lg font-bold mt-1 text-slate-800">${{fmtPct(tr["3m_pct"])}}</div></div>
                                <div class="bg-slate-50 p-4 rounded-xl border border-slate-100"><div class="text-xs text-slate-400 font-semibold">1-Year return (Abs)</div><div class="text-lg font-bold mt-1 text-slate-800">${{fmtPct(tr["1y_abs_pct"])}}</div></div>
                                <div class="bg-slate-50 p-4 rounded-xl border border-slate-100"><div class="text-xs text-slate-400 font-semibold">3-Year CAGR</div><div class="text-lg font-bold mt-1 text-emerald-600">${{fmtPct(tr["3y_cagr_pct"])}}</div></div>
                                <div class="bg-slate-50 p-4 rounded-xl border border-slate-100"><div class="text-xs text-slate-400 font-semibold">5-Year CAGR</div><div class="text-lg font-bold mt-1 text-emerald-600">${{fmtPct(tr["5y_cagr_pct"])}}</div></div>
                                <div class="bg-slate-50 p-4 rounded-xl border border-slate-100"><div class="text-xs text-slate-400 font-semibold">10-Year CAGR</div><div class="text-lg font-bold mt-1 text-emerald-600">${{fmtPct(tr["10y_cagr_pct"])}}</div></div>
                                <div class="bg-slate-50 p-4 rounded-xl border border-slate-100"><div class="text-xs text-slate-400 font-semibold">Since Inception CAGR</div><div class="text-lg font-bold mt-1 text-slate-800">${{fmtPct(tr["since_inception_cagr_pct"])}}</div></div>
                            </div>
                        </div>
                        <div>
                            <h4 class="text-sm font-bold uppercase text-slate-400 tracking-wider mb-3">Extremes & Anomalies</h4>
                            <div class="space-y-2">
                                <div class="flex justify-between items-center py-2.5 px-4 bg-emerald-50 text-emerald-800 rounded-lg"><span class="font-bold">🚀 Best Single Day</span><span class="font-extrabold">${{fmtPct(ex.best_day_pct)}} (${{ex.best_day_date || 'n/a'}})</span></div>
                                <div class="flex justify-between items-center py-2.5 px-4 bg-rose-50 text-rose-800 rounded-lg"><span class="font-bold">⚠️ Worst Single Day</span><span class="font-extrabold">${{fmtPct(ex.worst_day_pct)}} (${{ex.worst_day_date || 'n/a'}})</span></div>
                                <div class="flex justify-between items-center py-2.5 px-4 bg-emerald-50 text-emerald-800 rounded-lg"><span class="font-bold">📈 Best Single Month</span><span class="font-extrabold">${{fmtPct(ex.best_month_pct)}} (${{ex.best_month_date || 'n/a'}})</span></div>
                                <div class="flex justify-between items-center py-2.5 px-4 bg-rose-50 text-rose-800 rounded-lg"><span class="font-bold">📉 Worst Single Month</span><span class="font-extrabold">${{fmtPct(ex.worst_month_pct)}} (${{ex.worst_month_date || 'n/a'}})</span></div>
                            </div>
                        </div>
                    </div>
                `;
            }} else if (tabName === 'yearly') {{
                const cy = fund.calendar_year_returns || {{}};
                const fy = fund.financial_year_returns || {{}};
                
                let cyRows = '';
                Object.keys(cy).sort().reverse().forEach(year => {{
                    const label = year.includes('ytd') ? 'Current YTD' : year.replace('_pct', '');
                    const val = cy[year];
                    const colorClass = val >= 0 ? 'text-emerald-600' : 'text-rose-600';
                    cyRows += `<tr class="border-b border-slate-100"><td class="py-2.5 font-bold">${{label}}</td><td class="py-2.5 text-right font-extrabold ${{colorClass}}">${{fmtPct(val)}}</td></tr>`;
                }});
                
                let fyRows = '';
                Object.keys(fy).sort().reverse().forEach(year => {{
                    const label = year.includes('ytd') ? 'Current FY YTD' : year.replace('_pct', '').toUpperCase();
                    const val = fy[year];
                    const colorClass = val >= 0 ? 'text-emerald-600' : 'text-rose-600';
                    fyRows += `<tr class="border-b border-slate-100"><td class="py-2.5 font-bold">${{label}}</td><td class="py-2.5 text-right font-extrabold ${{colorClass}}">${{fmtPct(val)}}</td></tr>`;
                }});

                contentDiv.innerHTML = `
                    <div class="grid grid-cols-2 gap-8 h-full">
                        <div>
                            <h4 class="text-xs font-black uppercase text-slate-400 tracking-wider mb-3">Calendar Year Returns</h4>
                            <div class="max-h-[350px] overflow-y-auto pr-2">
                                <table class="w-full text-sm">
                                    <tbody class="divide-y divide-slate-100">
                                        ${{cyRows || '<tr><td class="py-4 text-slate-400 text-center font-bold">No calendar year history</td></tr>'}}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                        <div>
                            <h4 class="text-xs font-black uppercase text-slate-400 tracking-wider mb-3">Financial Year Returns</h4>
                            <div class="max-h-[350px] overflow-y-auto pr-2">
                                <table class="w-full text-sm">
                                    <tbody class="divide-y divide-slate-100">
                                        ${{fyRows || '<tr><td class="py-4 text-slate-400 text-center font-bold">No financial year history</td></tr>'}}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                `;
            }} else if (tabName === 'rolling') {{
                const rr = fund.rolling_returns || {{}};
                let cardsHtml = '';
                
                Object.keys(rr).sort().forEach(winKey => {{
                    const win = rr[winKey];
                    if (!win) return;
                    
                    const label = winKey.replace('y_window', '-Year');
                    cardsHtml += `
                        <div class="border border-slate-200 bg-slate-50/50 p-5 rounded-2xl">
                            <h5 class="font-extrabold text-sm text-slate-800 border-b border-slate-200 pb-2 mb-3">🔄 Rolling ${{label}} Distribution</h5>
                            <div class="grid grid-cols-2 gap-3 text-xs font-bold text-slate-600">
                                <div>Total Windows: <span class="text-slate-800 font-black">${{win.samples}}</span></div>
                                <div>Average CAGR: <span class="text-emerald-600 font-black">${{fmtPct(win.mean_pct)}}</span></div>
                                <div>Minimum CAGR: <span class="text-rose-500 font-black">${{fmtPct(win.min_pct)}}</span></div>
                                <div>Maximum CAGR: <span class="text-emerald-500 font-black">${{fmtPct(win.max_pct)}}</span></div>
                                <div>25th Percentile: <span class="text-slate-700 font-black">${{fmtPct(win.p25_pct)}}</span></div>
                                <div>75th Percentile: <span class="text-slate-700 font-black">${{fmtPct(win.p75_pct)}}</span></div>
                                <div>Median CAGR: <span class="text-emerald-600 font-black">${{fmtPct(win.median_pct)}}</span></div>
                                <div>Negative Windows: <span class="font-black ${{win.pct_negative > 0 ? "text-rose-600" : "text-emerald-600"}}">${{win.pct_negative.toFixed(2)}}%</span></div>
                            </div>
                            <div class="mt-3 bg-emerald-50 text-emerald-800 py-1.5 px-3 rounded-lg text-xs font-black flex justify-between">
                                <span>🚀 Windows outperforming > 12%:</span>
                                <span>${{win.pct_above_12.toFixed(2)}}%</span>
                            </div>
                        </div>
                    `;
                }});
                
                contentDiv.innerHTML = `
                    <div class="space-y-6">
                        <div class="space-y-4">
                            ${{cardsHtml || '<p class="text-slate-400 text-center font-bold">No rolling window metrics available</p>'}}
                        </div>
                    </div>
                `;
            }}
        }}

        // --- OVERLAP MATRIX MODAL JS ENGINE ---
        function openOverlapModal() {{
            const container = document.getElementById('overlap-modal-container');
            const panel = document.getElementById('overlap-modal-panel');
            
            container.classList.remove('opacity-0', 'pointer-events-none');
            panel.classList.remove('translate-y-12');
            
            // Generate the matrix dynamically if not already drawn
            drawOverlapMatrix();
        }}

        function closeOverlapModal() {{
            const container = document.getElementById('overlap-modal-container');
            const panel = document.getElementById('overlap-modal-panel');
            
            container.classList.add('opacity-0', 'pointer-events-none');
            panel.classList.add('translate-y-12');
        }}

        // Close on background click
        document.getElementById('overlap-modal-container').onclick = function(e) {{
            if (e.target === this) closeOverlapModal();
        }};

        function calculatePairwiseOverlap(holdingsA, holdingsB) {{
            if (!holdingsA || !holdingsB) return {{ total: 0.0, stocks: [] }};
            
            const mapB = {{}};
            holdingsB.forEach(h => {{
                const key = h.sid ? h.sid : h.company_name.toLowerCase().trim();
                mapB[key] = h;
            }});
            
            let overlap_pct = 0.0;
            const overlappingStocks = [];
            
            holdingsA.forEach(hA => {{
                const keyA = hA.sid ? hA.sid : hA.company_name.toLowerCase().trim();
                if (mapB[keyA]) {{
                    const hB = mapB[keyA];
                    const intersection = Math.min(hA.allocation_pct, hB.allocation_pct);
                    overlap_pct += intersection;
                    overlappingStocks.push({{
                        name: hA.company_name,
                        ticker: hA.ticker || 'n/a',
                        alloc_a: hA.allocation_pct,
                        alloc_b: hB.allocation_pct,
                        intersection: intersection
                    }});
                }}
            }});
            
            overlappingStocks.sort((a, b) => b.intersection - a.intersection);
            return {{
                total: parseFloat(overlap_pct.toFixed(2)),
                stocks: overlappingStocks
            }};
        }}

        function drawOverlapMatrix() {{
            const container = document.getElementById('overlap-matrix-container');
            container.innerHTML = '';
            
            // Extract funds that have holdings
            if (!combined || !combined.fund_holdings) {{
                container.innerHTML = '<div class="text-slate-400 font-bold text-center py-12">No fund holdings data found in cache! Please run portfolio_map_main.py locally first.</div>';
                return;
            }}
            
            // Map code to displays
            const fundsWithHoldings = dataset.filter(f => combined.fund_holdings[f.scheme_code]);
            if (fundsWithHoldings.length === 0) {{
                container.innerHTML = '<div class="text-slate-400 font-bold text-center py-12">No matching fund portfolios found!</div>';
                return;
            }}
            
            // Create Table Grid
            const table = document.createElement('table');
            table.className = 'w-full text-center border-collapse border border-slate-200 text-xs font-semibold';
            
            // 1. Header row
            const thead = document.createElement('thead');
            const headerTr = document.createElement('tr');
            headerTr.className = 'bg-slate-100 border-b border-slate-200';
            
            const cornerTh = document.createElement('th');
            cornerTh.className = 'p-3 text-left font-extrabold text-slate-500 border border-slate-200';
            cornerTh.textContent = 'Fund Name / Code';
            headerTr.appendChild(cornerTh);
            
            fundsWithHoldings.forEach(f => {{
                const th = document.createElement('th');
                th.className = 'p-3 font-extrabold text-slate-500 border border-slate-200';
                th.textContent = f.scheme_name.substring(0, 10) + '...';
                th.title = f.scheme_name;
                headerTr.appendChild(th);
            }});
            thead.appendChild(headerTr);
            table.appendChild(thead);
            
            // 2. Rows
            const tbody = document.createElement('tbody');
            fundsWithHoldings.forEach((fundA, idxA) => {{
                const tr = document.createElement('tr');
                tr.className = 'border-b border-slate-200 hover:bg-slate-50/50';
                
                // Left Label
                const tdLabel = document.createElement('td');
                tdLabel.className = 'p-3 text-left font-bold text-slate-800 border border-slate-200 bg-slate-50';
                tdLabel.textContent = fundA.scheme_name.substring(0, 18) + '...';
                tdLabel.title = fundA.scheme_name;
                tr.appendChild(tdLabel);
                
                // Cells
                fundsWithHoldings.forEach((fundB, idxB) => {{
                    const tdCell = document.createElement('td');
                    tdCell.className = 'p-3 border border-slate-200 transition-colors font-bold cursor-pointer';
                    
                    if (fundA.scheme_code === fundB.scheme_code) {{
                        tdCell.className += ' bg-slate-100 text-slate-500';
                        tdCell.textContent = '100.0%';
                    }} else {{
                        const holdingsA = combined.fund_holdings[fundA.scheme_code];
                        const holdingsB = combined.fund_holdings[fundB.scheme_code];
                        const overlapRes = calculatePairwiseOverlap(holdingsA, holdingsB);
                        
                        tdCell.textContent = `${{overlapRes.total.toFixed(2)}}%`;
                        
                        // Apply heatmap colors
                        if (overlapRes.total >= 20.0) {{
                            tdCell.className += ' bg-rose-50 hover:bg-rose-100 text-rose-800';
                        }} else if (overlapRes.total >= 10.0) {{
                            tdCell.className += ' bg-amber-50 hover:bg-amber-100 text-amber-800';
                        }} else {{
                            tdCell.className += ' bg-emerald-50 hover:bg-emerald-100 text-emerald-800';
                        }}
                        
                        tdCell.onclick = () => showOverlapDetails(fundA, fundB, overlapRes);
                    }}
                    tr.appendChild(tdCell);
                }});
                tbody.appendChild(tr);
            }});
            table.appendChild(tbody);
            container.appendChild(table);
        }}

        function showOverlapDetails(fundA, fundB, overlapRes) {{
            document.getElementById('overlap-details-title').innerHTML = `
                🔥 OVERLAP DETAILED BREAKDOWN: <br>
                <span class="text-slate-800 font-extrabold">${{fundA.scheme_name}}</span> <br>
                <span class="text-slate-400 font-bold text-xs lowercase">vs</span> <br>
                <span class="text-slate-800 font-extrabold">${{fundB.scheme_name}}</span> <br>
                <div class="mt-2 text-rose-600 font-black text-sm">Combined Overlap: ${{overlapRes.total.toFixed(2)}}%</div>
            `;
            
            const detailContainer = document.getElementById('overlap-details-body');
            detailContainer.innerHTML = '';
            
            if (overlapRes.stocks.length === 0) {{
                detailContainer.innerHTML = '<div class="text-slate-400 text-center py-12">No overlapping stock holdings found!</div>';
                return;
            }}
            
            const listContainer = document.createElement('div');
            listContainer.className = 'flex flex-col gap-4 w-full text-xs font-semibold text-slate-700 bg-white p-5 rounded-2xl border border-slate-200 shadow-sm';
            
            // Header indicators
            const listHeader = document.createElement('div');
            listHeader.className = 'flex justify-between border-b border-slate-200 pb-2 mb-2 font-black text-slate-400 uppercase text-[10px] tracking-wider';
            listHeader.innerHTML = '<span>Stock Holding Name</span><span>Overlap Contribution</span>';
            listContainer.appendChild(listHeader);

            // Compute 90% relevance rule in JS!
            const targetOverlapSum = 0.90 * overlapRes.total;
            let cumulativeOverlap = 0.0;
            const topStocks = [];
            const remainingStocks = [];
            
            overlapRes.stocks.forEach(st => {{
                if (cumulativeOverlap < targetOverlapSum) {{
                    topStocks.push(st);
                    cumulativeOverlap += st.intersection;
                }} else {{
                    remainingStocks.push(st);
                }}
            }});
            
            topStocks.forEach(st => {{
                const itemDiv = document.createElement('div');
                itemDiv.className = 'flex flex-col gap-1';
                
                const barWidth = (st.intersection / topStocks[0].intersection) * 100.0;
                
                itemDiv.innerHTML = `
                    <div class="flex justify-between font-bold">
                        <span>${{st.name}} <span class="text-[10px] text-slate-400 font-bold">(${{st.ticker}})</span></span>
                        <span class="font-extrabold text-slate-900">${{st.intersection.toFixed(2)}}%</span>
                    </div>
                    <div class="flex justify-between text-[10px] text-slate-400 font-semibold mb-1">
                        <span>Allocation A: ${{st.alloc_a.toFixed(2)}}%</span>
                        <span>Allocation B: ${{st.alloc_b.toFixed(2)}}%</span>
                    </div>
                    <div class="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
                        <div class="h-full bg-rose-500 rounded-full" style="width: ${{barWidth}}%"></div>
                    </div>
                `;
                listContainer.appendChild(itemDiv);
            }});
            
            if (remainingStocks.length > 0) {{
                const otherDiv = document.createElement('div');
                otherDiv.className = 'border-t border-slate-100 pt-3 text-[11px] text-slate-400 leading-normal font-semibold';
                const names = remainingStocks.map(s => s.name).join(', ');
                otherDiv.innerHTML = `<strong>Other overlapping stocks:</strong> ${{names}}`;
                listContainer.appendChild(otherDiv);
            }}
            
            detailContainer.appendChild(listContainer);
        }}
    </script>
</body>
</html>
"""

    try:
        OUTPUT_FILE_PATH.write_text(html_template, encoding="utf-8")
        print("\n" + "=" * 110)
        print(f"🎉 SUCCESS! Super-premium interactive dashboard successfully generated at: {OUTPUT_FILE_PATH}")
        print("Double-click the 'dashboard.html' file on your Mac to explore trailing, yearly, and rolling returns!")
        print("=" * 110 + "\n")
        log.info("Interactive Dashboard successfully written to %s", OUTPUT_FILE_PATH)
        return 0
    except Exception as e:
        log.exception("Failed to write HTML dashboard file:")
        print(f"\n❌ Error: Failed to generate dashboard.html: {e}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
