"""Interactive HTML Dashboard Generator for Mutual Fund Analytics.

Parses all processed JSON metrics inside ``data/fund_returns/`` and compiles
them into a self-contained, responsive ``dashboard.html`` webpage with
interactive charts (Risk vs Return, SIP Returns, Sharpe/Sortino/Calmar Ratios).
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

    # 1. Parse and Aggregate the fund datasets
    aggregated_data = []
    
    for jf in json_files:
        try:
            with jf.open("r", encoding="utf-8") as f:
                fund_data = json.load(f)
                
            tr = fund_data.get("trailing_returns") or {}
            sip = fund_data.get("hypothetical_sip_xirr") or {}
            risk = fund_data.get("risk") or {}
            ra = fund_data.get("risk_adjusted") or {}
            
            # Pack metrics, defaulting to None if missing so JavaScript can handle them gracefully
            aggregated_data.append({
                "code": fund_data.get("scheme_code"),
                "name": fund_data.get("scheme_name", "?"),
                "nav": fund_data.get("history", {}).get("latest_nav"),
                "as_of": fund_data.get("history", {}).get("latest_nav_date"),
                
                # Trailing returns
                "ret_1y": tr.get("1y_abs_pct"),
                "ret_3y": tr.get("3y_cagr_pct"),
                "ret_5y": tr.get("5y_cagr_pct"),
                "ret_10y": tr.get("10y_cagr_pct"),
                "ret_inception": tr.get("since_inception_cagr_pct"),
                
                # SIP returns
                "sip_3y": sip.get("3y_xirr_pct"),
                "sip_5y": sip.get("5y_xirr_pct"),
                "sip_10y": sip.get("10y_xirr_pct"),
                
                # Volatility/Risk
                "sd_3y": risk.get("sd_3y_pct"),
                
                # Performance Ratios
                "sharpe_3y": ra.get("sharpe_3y"),
                "sortino_3y": ra.get("sortino_3y"),
                "calmar_3y": ra.get("calmar_3y"),
            })
            log.info("Successfully loaded data for: %s", fund_data.get("scheme_name"))
        except Exception as e:
            log.warning("Failed to parse fund returns file %s: %s", jf, e)

    if not aggregated_data:
        log.error("Failed to parse any valid fund returns JSON records.")
        return 2

    # Sort funds alphabetically by name for clean displays
    aggregated_data.sort(key=lambda x: x["name"])

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
<body class="text-slate-800 antialiased min-h-screen">

    <div class="max-w-[1400px] mx-auto p-4 md:p-8">
        
        <!-- Header -->
        <header class="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-200 pb-6 mb-8">
            <div>
                <h1 class="text-3xl font-extrabold text-slate-900 tracking-tight">📈 MFHelper Portfolio Dashboard</h1>
                <p class="text-slate-500 mt-1 text-sm">Interactive performance & risk metrics analyzer across all mutual funds</p>
            </div>
            <div class="bg-white border border-slate-200 px-4 py-3 rounded-xl shadow-sm text-right">
                <div class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Last updated (IST)</div>
                <div class="text-sm font-bold text-slate-700 mt-0.5">{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
            </div>
        </header>

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
                <p class="text-xs text-slate-400 font-semibold mt-0.5">Double-check and audit the exact numerical statistics calculated across all mutual fund portfolios</p>
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
                    <tbody class="divide-y divide-slate-100 text-slate-700 font-medium">
                        <!-- Javascript will dynamically build row content here -->
                    </tbody>
                </table>
            </div>
        </section>

    </div>

    <!-- Data Injection -->
    <script id="portfolio-data" type="application/json">
        {json.dumps(aggregated_data)}
    </script>

    <script>
        const dataset = JSON.parse(document.getElementById('portfolio-data').textContent);
        console.log("Loaded dataset size:", dataset.length);

        // --- Helper formatting ---
        const fmtPct = (val) => (val !== null && val !== undefined) ? `${{val.toFixed(2)}}%` : 'n/a';
        const fmtNum = (val) => (val !== null && val !== undefined) ? val.toFixed(2) : 'n/a';

        // --- Populate KPIs ---
        let topCagr = -Infinity, topCagrName = '-';
        let topSip = -Infinity, topSipName = '-';
        let topSharpe = -Infinity, topSharpeName = '-';
        let lowestSd = Infinity, lowestSdName = '-';

        dataset.forEach(fund => {{
            if (fund.ret_3y && fund.ret_3y > topCagr) {{
                topCagr = fund.ret_3y; topCagrName = fund.name;
            }}
            if (fund.sip_3y && fund.sip_3y > topSip) {{
                topSip = fund.sip_3y; topSipName = fund.name;
            }}
            if (fund.sharpe_3y && fund.sharpe_3y > topSharpe) {{
                topSharpe = fund.sharpe_3y; topSharpeName = fund.name;
            }}
            if (fund.sd_3y && fund.sd_3y < lowestSd) {{
                lowestSd = fund.sd_3y; lowestSdName = fund.name;
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
        const tbody = document.querySelector('tbody');
        dataset.forEach(fund => {{
            const tr = document.createElement('tr');
            tr.className = 'hover:bg-slate-50/50 transition-colors';
            tr.innerHTML = `
                <td class="py-3 px-4 font-bold text-slate-800">
                    <div class="truncate max-w-[320px]">${{fund.name}}</div>
                    <span class="text-xs text-slate-400 font-semibold">AMFI: ${{fund.code}}</span>
                </td>
                <td class="py-3 px-4 text-center text-slate-600">${{fmtPct(fund.ret_1y)}}</td>
                <td class="py-3 px-4 text-center font-bold text-slate-900">${{fmtPct(fund.ret_3y)}}</td>
                <td class="py-3 px-4 text-center text-slate-600">${{fmtPct(fund.ret_5y)}}</td>
                <td class="py-3 px-4 text-center text-slate-600">${{fmtPct(fund.sip_3y)}}</td>
                <td class="py-3 px-4 text-center text-slate-600">${{fmtPct(fund.sip_5y)}}</td>
                <td class="py-3 px-4 text-center text-slate-600">${{fmtPct(fund.sd_3y)}}</td>
                <td class="py-3 px-4 text-center font-bold text-amber-700">${{fmtNum(fund.sharpe_3y)}}</td>
                <td class="py-3 px-4 text-center text-slate-600">${{fmtNum(fund.sortino_3y)}}</td>
                <td class="py-3 px-4 text-center text-slate-600">${{fmtNum(fund.calmar_3y)}}</td>
            `;
            tbody.appendChild(tr);
        }});

        // --- CHART 1: Efficient Frontier (Scatter Plot) ---
        const scatterData = dataset
            .filter(f => f.sd_3y !== null && f.ret_3y !== null)
            .map(f => ({{
                x: f.sd_3y,
                y: f.ret_3y,
                label: f.name
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
        const ratioLabels = dataset.map(f => f.name.substring(0, 15) + '...');
        const sharpeSeries = dataset.map(f => f.sharpe_3y);
        const sortinoSeries = dataset.map(f => f.sortino_3y);
        const calmarSeries = dataset.map(f => f.calmar_3y);

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
        const sipLabels = dataset.map(f => f.name.substring(0, 20) + '...');
        const sip3ySeries = dataset.map(f => f.sip_3y);
        const sip5ySeries = dataset.map(f => f.sip_5y);
        const sip10ySeries = dataset.map(f => f.sip_10y);

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
    </script>
</body>
</html>
"""

    try:
        OUTPUT_FILE_PATH.write_text(html_template, encoding="utf-8")
        print("\n" + "=" * 110)
        print(f"🎉 SUCCESS! Interactive performance & risk dashboard successfully generated at: {OUTPUT_FILE_PATH}")
        print("Double-click the 'dashboard.html' file on your Mac to explore your mutual funds interactively!")
        print("=" * 110 + "\n")
        log.info("Interactive Dashboard successfully written to %s", OUTPUT_FILE_PATH)
        return 0
    except Exception as e:
        log.exception("Failed to write HTML dashboard file:")
        print(f"\n❌ Error: Failed to generate dashboard.html: {e}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
