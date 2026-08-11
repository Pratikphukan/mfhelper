# Design: Per-Fund Historical Drilldown Report

## 1. System Architecture Data Flow

```
                           [CLI Arguments]
                         --code & --days
                                │
                                ▼
                       [fetch_history]
                     Downloads NAV history
                      from api.mfapi.in
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│              compute_historical_rows() loop                      │
│                                                                 │
│   For date inside trailing N trading days:                      │
│     - NAV: raw value on date                                    │
│     - Day Change %: vs. (date - 1)                              │
│     - Dist from 52W High %: trailing 365 days from date         │
│     - Dist from 200D SMA %: trailing 200 trading days from date │
│     - RSI (14): smoothed Wilder RSI up to date                  │
└───────────────────────────────┬─────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│               HistoricalSheetWriter rendering                    │
│                                                                 │
│   - Creates a tab (e.g. "Nippon Small Cap 30D")                 │
│   - Writes Info Banner row (merged, italicized, blue background) │
│   - Writes Headers                                              │
│   - Formats columns natively (Date, Decimals, Percent, RSI)     │
└─────────────────────────────────────────────────────────────────┘
```

## 2. Technical Challenges & Solutions

### A. Subsetting vs. Lookbacks
Although the user only requests the last $N$ days of metrics to display (e.g. 30 days), each of those individual days requires looking back into the past (up to 365 calendar days for the 52W High and 200 trading days for the 200D SMA). 
* **Solution:** We download and sort the **entire historical NAV series** first, and then run lookback computations for only the newest $N$ days.

### B. RSI Continuity
Wilder RSI requires continuous exponential-style smoothing from the fund's inception to remain highly accurate and match what the daily scheduler prints on active runs.
* **Solution:** The calculation engine seeds its RSI calculations from the fund's absolute inception and walks forward to prevent point-to-point calculation discrepancies.

---

## 3. Google Sheets Template & Layout

### Row 1: Info Banner
A merged, bold, and italicized header cell styled with a light blue fill background `#EBF2FF` and left-padding:
`[Fund Name] | AMFI [Scheme Code] | last [Days] NAV-publish days | updated [Timestamp IST]`

### Row 2: Table Header
Bold, centered, and light grey background.

| Date | NAV | Day Change % | Dist from 52W High % | Dist from 200D SMA % | RSI (14) |
| :--- | :--- | :--- | :--- | :--- | :--- |

### Row 3 onwards: Daily Records (Newest First)
* Dates are displayed as `YYYY-MM-DD`.
* NAVs are displayed with 4 decimals (`0.0000`).
* Day Change %, 52W High %, and 200D SMA % are displayed as formatted percentages (`0.00%`).
* RSI (14) is displayed with 2 decimals (`0.00`).
* Missing history fields (e.g. at the dawn of a fund's timeline) are automatically left blank.
