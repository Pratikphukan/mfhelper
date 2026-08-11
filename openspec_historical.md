# OpenSpec: Per-Fund Historical Drilldown Report

This specification documents the architecture, parameters, and layout for the on-demand, single-fund historical drilldown capability in **MFHelper**.

---

## 1. Objective
Extract the daily historical performance and technical indicators of a **single, specific mutual fund** over a fully configurable window of trailing trading days, and render the results vertically as a chronological timeline (newest first) in its own dedicated Google Sheet tab.

---

## 2. Command-Line Interface (CLI)

The CLI entry point `historical_main.py` supports fully configurable parameters:

```bash
.venv/bin/python historical_main.py --code <SCHEME_CODE> --days <DAYS> --tab <CUSTOM_TAB_NAME>
```

### Parameters:
* `--code` *(Required)*: The 6-digit AMFI scheme code (e.g. `147946` for Bandhan Small Cap).
* `--days` *(Optional, Default: 30)*: The number of historical trading days to compute and write. 
* `--tab` *(Optional)*: A custom name for the tab. If omitted, a clean title is dynamically derived from the fund name + the days count (e.g. `"Nippon Small Cap 60D"`).
* `--dry-run` *(Optional)*: Runs the calculations and formats the table in the console without writing to the Google Sheet.

---

## 3. Data Processing & Metric Engine

For every NAV-publish date in the configured trailing window, the processing engine (`mfhelper/historical.py`) computes each metric **as it would have looked on that historical date**:

1. **NAV:** The actual published NAV on that date.
2. **Day Change %:** Percentage change compared to the *prior trading day's NAV* (not calendar day).
3. **Distance from 52-Week High %:** Percentage distance from the highest NAV in the trailing 365 calendar days ending on that specific date.
4. **Distance from 200-Day SMA %:** Percentage distance from the 200-day Simple Moving Average calculated over the 200 trading days ending on that date.
5. **RSI (14):** Wilder's 14-day RSI, seeded and smoothed continuously from the fund's inception up to that specific date.

---

## 4. Google Sheets Layout (`mfhelper/historical_sheet.py`)

Each run creates or overwrites a dedicated tab with a vertical timeline table:

### Row 1: Info Banner
A merged, bold, and italicized header cell across all columns detailing:
`[Fund Name] | AMFI [Scheme Code] | last [Days] NAV-publish days | updated [Timestamp IST]`

### Row 2: Table Header
| Date | NAV | Day Change % | Dist from 52W High % | Dist from 200D SMA % | RSI (14) |
| :--- | :--- | :--- | :--- | :--- | :--- |

### Row 3 onwards: Daily Records (Newest First)
* Dates are displayed as `YYYY-MM-DD`.
* NAVs are displayed with 4 decimals (`0.0000`).
* Day Change %, 52W High %, and 200D SMA % are displayed as formatted percentages (`0.00%`).
* RSI (14) is displayed with 2 decimals (`0.00`).
* If a metric does not have enough history on an older date (e.g., fewer than 200 days of history for 200D SMA), the cell is automatically left blank.
