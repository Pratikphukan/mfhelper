# MFHelper

A small Python job that:

1. Downloads AMFI's daily NAV dump (https://www.amfiindia.com/spages/NAVAll.txt)
2. Picks out the funds you care about
3. Computes day-change % against the previous run's NAV
4. Computes distance from the trailing 52-week high (using mfapi.in for history)
5. Computes distance from the 200-day Simple Moving Average (same mfapi.in history)
6. Computes RSI (14-day, Wilder smoothing) from the same history
7. Appends one row per run to a Google Sheet (wide format: five sub-columns per fund)
8. Trims the sheet so it always holds a rolling window of the **30 most recent run-dates**

Runs automatically every day at **10:30 AM IST** via macOS `launchd`.

---

## Sheet layout

Wide format: funds are **columns** (grouped with a merged header), runs are **rows**.

Row 1 holds fund names (each merged across **five** sub-columns). Row 2 holds `NAV`, `Day Change %`, `Dist from 52W High %`, `Dist from 200D SMA %`, and `RSI (14)` labels. Row 3 onwards is one row per run:

```
|                     |                    Parag Parikh Flexi Cap                        |                    Mirae Asset Large Cap                        |
| Run Timestamp (IST) |   NAV   | Day Change % | Dist 52W H% | Dist 200D SMA% | RSI (14) |   NAV   | Day Change % | Dist 52W H% | Dist 200D SMA% | RSI (14) |
| 2026-05-07 10:30:03 | 82.9104 |    0.56%     |   -2.84%    |     5.21%      |  62.40   | 117.9801|   -0.30%     |   -1.91%    |     2.45%      |  54.18   |
| 2026-05-08 10:30:02 | 83.1502 |    0.29%     |   -2.56%    |     5.43%      |  63.05   | 118.1205|    0.12%     |   -1.79%    |     2.51%      |  54.62   |
```

- `Run Timestamp (IST)` in column A is merged vertically across both header rows (so it reads cleanly).
- The first two rows are frozen so they stay visible when you scroll.
- Number formats: NAV shows 4 decimals; `Day Change %`, `Dist from 52W High %`, and `Dist from 200D SMA %` show 2 decimals with a `%` suffix; `RSI (14)` shows 2 decimals with no suffix (it's a 0-100 oscillator, not a percent).
- `Dist from 52W High %` is the percent distance from the highest NAV in the trailing 365 days (today's NAV included). It's always `<= 0.00%`; a fresh all-time-high prints `0.00%`.
- `Dist from 200D SMA %` is `(today's NAV - 200-day SMA) / 200-day SMA * 100`. Positive means today's NAV is above its 200-day average (long-term uptrend context); negative means below (long-term downtrend context). The 200-day window is the classical long-term trend filter used in equity charting. Window: the most recent **200 NAV-publish days** (trading days, not calendar days). The cell is left blank for funds with fewer than 200 days of available history.
- `RSI (14)` is the **14-day Relative Strength Index** with Wilder's smoothing (the textbook definition, what charting platforms call "RSI" by default). Computed from the chronological NAV series ending at today's NAV. Conventional bands: `> 70` overbought, `< 30` oversold, `50` neutral. Note that RSI was designed for stocks; mutual fund NAVs are inherently smoother (each NAV already averages many holdings), so the 70/30 thresholds trigger less often -- treat it as context, not a signal. The cell is left blank for funds with fewer than 15 NAV-publish days of history.
- On the first observation of a fund, its `Day Change %` cell is blank.
- On weekends/holidays when AMFI hasn't published a new NAV, the NAV is repeated from the previous trading day and day-change is `0.00%`.

---

## Adding or removing funds later

The column layout is **append-only** -- safe to add or remove funds without losing history.

- **Add a fund to `config/funds.yaml`:** on the next run, five new sub-columns appear at the rightmost position. Previous rows stay blank in those columns (they pre-date the fund). New rows get NAV, Day Change %, Dist 52W High %, Dist 200D SMA %, and RSI (14) filled in (the SMA cell stays blank until 200 NAV-publish days of history are available; the RSI cell stays blank until 15 NAV-publish days of history are available).
- **Remove a fund from `config/funds.yaml`:** its columns remain in the sheet (history preserved), but from that run onward its cells in new rows are blank.
- **Reorder funds in `config/funds.yaml`:** the sheet's column order does **not** change -- it's frozen to the historical add-order, tracked in `data/sheet_columns.json`.

> Keep `data/sheet_columns.json` in sync with the worksheet. If you clear the worksheet manually, also delete `data/sheet_columns.json` so the header gets rebuilt. If you delete only the state file, on the next run the script will think every fund is new and append a duplicate set of columns -- in that case, clear the worksheet too.

---

## One-time setup

### 1. Install dependencies

```bash
cd /Users/pratikphookan/PycharmProjects/MFHelper
python3 -m venv .venv        # skip if .venv already exists
.venv/bin/pip install -r requirements.txt
```

### 2. Create a Google Cloud OAuth client (for Sheets access with your own Google account)

1. Go to https://console.cloud.google.com/ and create (or select) a project.
2. Enable the **Google Sheets API** for that project (APIs & Services -> Library).
3. Configure the **OAuth consent screen**:
   - User type: **External**
   - Fill in app name, your email, and support email
   - Under **Test users**, add your own Google account
4. Create an **OAuth client ID**:
   - Application type: **Desktop app**
   - Any name
5. Click **Download JSON** and save the file to `config/credentials.json` in this project.

### 3. Create your Google Sheet

1. Create a new Google Sheet (or pick an existing one).
2. Copy the spreadsheet ID from the URL:
   `https://docs.google.com/spreadsheets/d/<THIS_PART_IS_THE_ID>/edit`
3. Paste it into `config/settings.yaml` under `google_sheet.spreadsheet_id`.
4. The first tab's name should match `google_sheet.worksheet` (default `Daily NAV`), or change the config to match your tab. If the named tab doesn't exist yet it will be auto-created.

### 4. Add your funds

Edit `config/funds.yaml`. The file currently has two placeholder entries -- replace them with your own funds. Each entry needs the AMFI scheme code; the name is optional.

Finding a scheme code:
- Open https://www.amfiindia.com/spages/NAVAll.txt in a browser
- Ctrl/Cmd-F for a distinctive word from your fund's name
- The leftmost number on the line is the scheme code

### 5. First run (does the OAuth handshake)

```bash
.venv/bin/python main.py
```

A browser window will open; sign in with your Google account and grant the Sheets scope. The refresh token is saved to `data/token.json` and all future runs are silent (no browser).

Verify: the Google Sheet now has a header row plus one row per configured fund.

### 6. Install the daily scheduler

```bash
chmod +x scripts/install_launchd.sh
./scripts/install_launchd.sh
```

This script:
- Copies `scripts/com.mfhelper.daily.plist` to `~/Library/LaunchAgents/` with the project's absolute path baked in
- Loads it into `launchd` so it fires daily at 10:30 AM local time

Verify:

```bash
launchctl list | grep com.mfhelper.daily
```

Manually trigger a run (useful for testing the scheduled path):

```bash
launchctl start com.mfhelper.daily
tail -f logs/stdout.log logs/stderr.log
```

---

## Migrating from earlier sheet layouts

The current layout is **5 sub-columns per fund** (NAV, Day Change %, Dist 52W H%, Dist 200D SMA %, RSI (14)). Older layouts and the previous 50-day SMA window auto-migrate in place on the next run; you don't need to clear the worksheet.

### From a sheet that ran with the 50-day SMA window (header reads "Dist from 50D SMA %")

The next run does a **rename + backfill** of the SMA column:

1. Renames the row 2 header from `Dist from 50D SMA %` to `Dist from 200D SMA %` for every fund group.
2. For each existing data row, recomputes the SMA distance using the 200-day window (with the NAV that's already stored in that row as the reference NAV) and overwrites the historical cell. Rows where mfapi.in doesn't have 200 days of history at the time of that past run-date end up blank.
3. Both steps go out as a single `batch_update` request, so the rename and backfill commit atomically.

Idempotent: subsequent runs see the new header and skip this step.

### From the 4-sub-column layout (... + Dist SMA %)

Nothing to do -- the next run runs a **4 -> 5 in-place migration**:

- For each existing fund group, the run unmerges the fund-name header, inserts a new empty column right after the existing `Dist from ... SMA %` column, re-merges the fund name across the now-5 sub-columns, writes the `RSI (14)` label, and applies the plain `0.00` number format.
- Historical rows stay exactly where they are; the new sub-column is left blank for past runs. Today's row is then appended with the RSI value filled in (or blank if mfapi.in has fewer than 15 days of history for that fund).
- If the existing SMA header still reads `Dist from 50D SMA %`, the rename + backfill above runs after the 4 -> 5 step.

### From the 3-sub-column layout (NAV + Day Change % + Dist 52W H%)

The next run runs a **3 -> 4 -> 5 chained migration** in the same execution:

1. **3 -> 4:** insert a `Dist from 200D SMA %` column right after each fund's `Dist from 52W High %`.
2. **4 -> 5:** insert an `RSI (14)` column right after each fund's `Dist from 200D SMA %`.

### From the legacy 2-sub-column layout (NAV + Day Change % only)

The next run runs a full **2 -> 3 -> 4 -> 5 chained migration**:

1. **2 -> 3:** insert a `Dist from 52W High %` column right after each fund's `Day Change %`.
2. **3 -> 4:** insert a `Dist from 200D SMA %` column.
3. **4 -> 5:** insert an `RSI (14)` column.

All historical rows are preserved; the new sub-columns are blank for older rows.

### Migration mechanics and caveats (applies to all chains)

- Migrations are idempotent at the layout level: subsequent runs see the new sub-column count and skip migration entirely.
- API-call cost scales with fund count and chain length: roughly 5 Sheets API calls per fund per migration step. With ~8 funds, a single-step 4 -> 5 migration uses ~40 calls; a chained 3 -> 4 -> 5 uses ~80; the full 2 -> 5 chain uses ~120. All are within Sheets' 60-writes/min/user quota when paced, but worth knowing.
- If a migration is interrupted partway through (network blip, quota exhaustion), the worksheet ends up in a partially migrated state with mixed column widths across funds. **In-place recovery from a partial migration is not supported**: the safest fix is to clear the worksheet and delete `data/sheet_columns.json` + `data/last_nav.json`. To minimize this risk on a sheet with several funds, consider triggering the next run interactively (`./.venv/bin/python main.py`) rather than letting `launchd` do it cold -- especially if you're catching up across multiple migration steps.

### From the original long-format layout (one row per fund per run)

If you ran a much earlier version of this project that wrote one row per fund per run (with `NAV Date` / `Scheme Code` / `Prev NAV` / `Day Change (abs)` columns), you'll need to start fresh:

1. Clear the worksheet (delete all rows, or create a new worksheet and point `config/settings.yaml` at it).
2. Delete `data/sheet_columns.json` and `data/last_nav.json` if they exist.
3. Run `python main.py` -- it'll build the new five-sub-column header and append today's run row.

If you've never done the first OAuth run yet, this is a no-op: just proceed with the one-time setup above.

---

## Operational notes

- **Timing & AMFI publication:** AMFI posts each trading day's NAV between ~9 PM and 11 PM IST. A 10:30 AM run captures the **previous trading day's** NAV (which is finalised and correct).
- **Mac asleep at 10:30 AM?** `launchd` will run the job as soon as the Mac wakes up. That's the main reason we use `launchd` instead of `cron`.
- **Weekends/holidays:** the job still runs and writes a row (NAV unchanged, day-change = 0.00%). Those rows count toward the 30-day rolling window, matching the "30 job runs" interpretation.
- **Missing funds:** if a configured scheme code isn't in today's AMFI file, the job automatically falls back to `api.mfapi.in` (a third-party mirror of AMFI data that's often more complete during early-morning or holiday windows). If mfapi.in also doesn't have it (delisted, typo'd code, etc.), the job logs a warning, leaves that fund's cells blank in the row, and continues with a `1` exit code. See [mfhelper/mfapi.py](mfhelper/mfapi.py).
- **52W high / 200D SMA / RSI source:** all three metrics are computed from `api.mfapi.in/mf/<code>` history (one HTTP call per fund per run, served alongside the fallback NAV check above so we don't make redundant requests). The HTTP call uses a 20s connect / 30s read timeout and retries up to 3 times with exponential backoff (2s, 4s) on transient failures (timeouts, 5xx). If all retries exhaust for a particular fund, all three derived cells for that run are left blank but NAV and Day Change % are still written. The 200D SMA also stays blank for funds with fewer than 200 NAV-publish days of history; RSI also stays blank for funds with fewer than 15 NAV-publish days of history.
- **Network failure on AMFI:** job exits non-zero, no sheet write, state files untouched -- next day's run recovers cleanly.

---

## Project layout

```
MFHelper/
  main.py                        # daily NAV scheduler entry point
  analytics_main.py              # on-demand analytics report CLI
  historical_main.py             # on-demand per-fund N-day drilldown CLI
  backfill_main.py               # one-shot: fill historical Daily NAV rows for one fund
  returns_main.py                # one-shot: write per-fund returns JSON dump
  plot_main.py                   # one-shot: per-fund rolling-return PNGs (with benchmark overlay)
  mfhelper/
    __init__.py
    amfi.py                      # fetch + parse NAVAll.txt
    analytics.py                 # 1Y / 3Y / 5Y / 7Y / 10Y returns, SD, Sharpe, Sortino
    analytics_sheet.py           # writes the Fund Analytics tab
    columns.py                   # data/sheet_columns.json: ordered scheme codes
    config.py                    # YAML loaders with validation
    expense_ratio.py             # Groww-page scraper (with code validation)
    historical.py                # per-day backfill compute (last N publish-days per fund)
    historical_sheet.py          # writes the per-fund historical-drilldown tab
    metrics.py                   # 52-week-high distance, 200D SMA distance, RSI (Wilder)
    mfapi.py                     # mfapi.in: NAV history + fallback for codes missing from AMFI
    returns_calc.py              # full-bouquet returns: trailing/CY/FY/rolling/risk/SIP-XIRR
    returns_writer.py            # atomic per-fund JSON writer
    sheets.py                    # gspread + OAuth + 5-sub-col layout + auto-migration (2->5 chained)
    state.py                     # data/last_nav.json read/write
  config/
    funds.yaml                   # you edit: scheme codes to track daily
    analytics_funds.yaml         # you edit: scheme codes for the analytics report (separate list)
    settings.yaml                # you edit: sheet ID, history_days, timezone
    credentials.json             # you download from GCP (git-ignored)
  data/
    token.json                   # auto-generated OAuth refresh token (git-ignored)
    last_nav.json                # auto-generated prev-NAV state (git-ignored)
    sheet_columns.json           # auto-generated column-order state (git-ignored)
    fund_returns/                # per-fund JSON returns dump (git-ignored)
      {code}.json                #   one file per fund; regenerable from returns_main.py
  logs/
    mfhelper.log                 # daily-scheduler log
    mfhelper_analytics.log       # analytics-report log
    mfhelper_historical.log      # historical-drilldown log
    mfhelper_backfill.log        # one-shot backfill log
    mfhelper_returns.log         # per-fund returns dump log
    stdout.log / stderr.log      # launchd-captured streams
  scripts/
    com.mfhelper.daily.plist     # launchd template
    install_launchd.sh           # installer
  requirements.txt
  .gitignore
  README.md
```

---

## Fund Analytics report (on-demand)

A separate CLI for "long view" research metrics, independent from the
daily NAV scheduler. Pulls one row per fund into a fresh worksheet tab
(default name: **Fund Analytics**) of the same Google Sheet:

| Fund Name | Scheme Code | 1Y % | 3Y CAGR % | 5Y CAGR % | 7Y CAGR % | 10Y CAGR % | SD % | Sharpe | Sortino | Expense % | Last Updated (IST) |
|-----------|-------------|------|-----------|-----------|-----------|------------|------|--------|---------|-----------|--------------------|

### What each column means

- **1Y %** -- absolute (point-to-point) return over the trailing 365 days.
- **3Y / 5Y / 7Y / 10Y CAGR %** -- annualized compound growth rate over those windows. Cells stay blank if the fund's history is shorter than the window.
- **SD %** -- annualized standard deviation of daily log returns over the trailing 3 years. Annualization factor: √252.
- **Sharpe** -- `(3Y CAGR − 7%) / SD %`. 7% is the assumed risk-free rate (RBI repo proxy). Higher = better risk-adjusted return.
- **Sortino** -- `(3Y CAGR − 7%) / annualized downside deviation`. Like Sharpe, but only "punishes" negative-day volatility.
- **Expense %** -- current Total Expense Ratio (TER), scraped from Groww with AMFI-scheme-code validation. Manual override available.

### Run it

```bash
.venv/bin/python analytics_main.py                        # default tab "Fund Analytics"
.venv/bin/python analytics_main.py --tab "May 2026"        # write into a custom tab
.venv/bin/python analytics_main.py --no-expense-scrape     # skip TER scrape
.venv/bin/python analytics_main.py --dry-run               # compute, print, don't write
.venv/bin/python analytics_main.py --funds config/other.yaml
```

The tab is **overwritten on every run** (no historical preservation -- by design, this is a snapshot).

### Configuring the fund list

Edit `config/analytics_funds.yaml`. Same shape as `funds.yaml`, plus two optional per-fund fields:

```yaml
funds:
  - code: "119788"
    name: "SBI Gold Fund - Direct - Growth"
  - code: "120492"
    name: "JM Flexicap Fund - Direct - Growth"
    groww_slug: "jm-multi-strategy-fund-direct-growth"   # optional: legacy slug
  - code: "127042"
    name: "Motilal Oswal Midcap Fund - Direct - Growth"
    expense_ratio: 0.75                                  # optional: manual override
```

Field semantics:

- `code` -- AMFI scheme code (required).
- `name` -- display name (optional; mfapi.in's name is used if omitted).
- `expense_ratio` -- *manual override*, in percent. If set, the scrape is bypassed entirely. Use this when you want to be sure of the value, or when Groww doesn't list the fund.
- `groww_slug` -- *URL-fragment hint* for the Groww scrape. Groww's slugs sometimes encode a fund's *historical* name (e.g. "JM Flexicap Fund" lives at `/mutual-funds/jm-multi-strategy-fund-direct-growth` because it was once "JM Multi Strategy"). If the auto heuristic logs `Could not auto-fetch expense ratio for <code>`, open the fund on groww.in, copy the part after `/mutual-funds/` from the URL, and paste it here.

### How the expense-ratio scrape stays safe

Every Groww page candidate is parsed via its embedded `__NEXT_DATA__` JSON tree, and the `direct_scheme_code` / `scheme_code` field on the returned page must match the AMFI code we asked for. If it doesn't, that candidate is rejected and the next slug is tried. This prevents slug collisions (e.g. accidentally landing on the Regular plan instead of Direct) from returning a plausible-but-wrong number.

If no candidate validates, the cell is left blank and a single line is logged so you know which fund needs a `groww_slug` or `expense_ratio` override.

---

## Per-fund historical drilldown (on-demand)

A third CLI for "show me the last N days of NAV / Day Change % / 52W / 200D SMA / RSI for a single fund" -- one tab per fund, one row per NAV-publish day, newest first. Same five metrics as the daily NAV tab, but rendered as a vertical table for one fund at a time.

```bash
.venv/bin/python historical_main.py --code 118551                # last 30 days, default tab
.venv/bin/python historical_main.py --code 118551 --days 60      # last 60 days
.venv/bin/python historical_main.py --code 118551 --tab "FUSO 30D"
.venv/bin/python historical_main.py --code 118551 --dry-run      # print only
```

The tab is overwritten on each run. The first row of the tab is an info banner with the fund name, AMFI scheme code, window length, and last-updated timestamp; row 2 is the header; rows 3..N are the data, newest first.

### How each row is computed (it's a backfill, not just a copy of mfapi)

For every NAV-publish date in the trailing window, we recompute every metric *as it would have been on that date*:

- `NAV` -- the published NAV that day.
- `Day Change %` -- vs. the prior NAV-publish day's NAV. Filled even for the oldest row in the window (the comparison comes from the broader mfapi history that lives "before" the window starts).
- `Dist from 52W High %` -- max NAV in the trailing 365 calendar days ending at that date.
- `Dist from 200D SMA %` -- 200 NAV-publish days ending at that date. Cells stay blank if the fund had fewer than 200 publish days of history at that date.
- `RSI (14)` -- Wilder's 14-day RSI, with the EMA-style smoothing seeded from the start of the available history (so each row matches what the daily-NAV scheduler would have written that day). Cells stay blank if the fund had fewer than 15 publish days of history at that date.

### Finding the AMFI scheme code

If you only know the fund name, search mfapi.in:

```python
import requests
matches = requests.get("https://api.mfapi.in/mf/search", params={"q": "Franklin U.S."}).json()
for m in matches:
    print(m["schemeCode"], m["schemeName"])
```

Or open `https://www.amfiindia.com/spages/NAVAll.txt` and Cmd-F for a keyword from the fund's name -- the leftmost number on that line is the scheme code.

---

## Backfilling historical Daily NAV rows for one fund (on-demand)

When you add a fund to `config/funds.yaml` mid-stream, the **Daily NAV** tab's column for that fund is populated only for runs from the addition date onward -- earlier rows in the rolling 30-day window stay blank for it. The `backfill_main.py` CLI fills those gaps in place, **on the same Daily NAV tab** (not on a new tab -- that's what `historical_main.py` does).

```bash
.venv/bin/python backfill_main.py --code 118551 --dry-run   # preview, write nothing
.venv/bin/python backfill_main.py --code 118551             # actually write
.venv/bin/python backfill_main.py --code 118551 --overwrite # also rewrite non-blank cells
```

By default it writes only into cells that are currently blank. Today's row is preserved untouched. Each historical row is computed *as if the scheduler had been running back then*: NAV is the most recent mfapi.in publish on or before that run-date (so weekend rows correctly anchor on Friday's NAV with `Day Change %` = 0.00%), and 52W%/200D%/RSI all use the metric helpers from `mfhelper/metrics.py` -- bit-exact equivalents of what the live scheduler would have written.

### Layout-alignment guard

The script refuses to run if the worksheet's physical fund-group count doesn't match `data/sheet_columns.json`. That mismatch usually means an orphan column block (a fund removed from `funds.yaml` but still physically present in the sheet) needs to be deleted in Google Sheets first. Backfill into a misaligned sheet would scramble fund columns, so the script intentionally aborts with a message that tells you what to fix.

If you see the alignment error: open the sheet, delete the obsolete 5-column block of the fund you no longer want (or re-add its code to `data/sheet_columns.json` if you actually want to keep it), then re-run.

---

## Per-fund returns JSON dump (on-demand)

`returns_main.py` writes one structured JSON file per fund to `data/fund_returns/{code}.json` containing the full bouquet of return metrics computable from `mfapi.in` history alone. Designed for offline analysis, dashboards, or piping into other tools — every metric is a single key lookup, every date is ISO-8601, and the schema is versioned.

```bash
.venv/bin/python returns_main.py                       # all funds in funds.yaml
.venv/bin/python returns_main.py --code 118551         # one fund (repeatable)
.venv/bin/python returns_main.py --funds config/analytics_funds.yaml
.venv/bin/python returns_main.py --dry-run             # compute, don't write
.venv/bin/python returns_main.py --rfr 6.5             # custom risk-free rate
```

### What each JSON file contains

| Section | What's inside |
|---|---|
| `history` | First/latest NAV date, latest NAV, total publish-day count |
| `data_quality` | Auto-detected NAV unit-rebase discontinuities (>50% day-over-day jumps from scheme mergers); pre-rebase history is dropped from all calculations and the dropped events are listed for auditing |
| `trailing_returns` | 1D / 1W / 1M / 3M / 6M / YTD / 1Y absolute / 2Y / 3Y / 5Y / 7Y / 10Y / since-inception. Sub-1Y are absolute, multi-year are CAGR |
| `calendar_year_returns` | Per-CY (e.g. `2024_pct`) since inception, plus `current_year_ytd_pct` |
| `financial_year_returns` | Per-Indian-FY (e.g. `FY26_pct` covers Apr 2025 – Mar 2026), plus current-FY YTD |
| `rolling_returns` | For 1Y / 3Y / 5Y / 7Y windows: count of windows, min / p25 / median / p75 / max, mean, % of windows that finished negative, % that cleared 12% (the equity rule-of-thumb) |
| `risk` | Annualized SD of daily log returns over 3Y / 5Y / since-inception, downside deviation 3Y, max-drawdown analysis (peak/trough/recovery dates + duration in days), current drawdown |
| `risk_adjusted` | Sharpe / Sortino over 3Y and 5Y, Calmar 3Y. Risk-free rate defaults to 7% (RBI repo proxy), overridable via `--rfr` |
| `extremes` | Best/worst single-day NAV change with dates, best/worst calendar-month return |
| `hypothetical_sip_xirr` | ₹10,000/month SIP on the 1st (or next available NAV publish day), evaluated at 3Y / 5Y / 10Y horizons. Pure-Python bisection XIRR; horizons longer than the fund's history return `null` |
| `unavailable_metrics` | **Honest disclosure**: every metric I considered including but couldn't compute from `mfapi.in` alone, with the data source each one would need (real returns → World Bank CPI; alpha → benchmark index; actual XIRR → broker transaction history) |

### Output is git-ignored by default

The `data/fund_returns/` directory is in `.gitignore`. The JSON files are derived from `mfapi.in` and cheap to regenerate (~1s per fund on a warm network), so committing them would just spam the repo with churn on every refresh. If you ever want to freeze a snapshot for archival, copy the directory elsewhere first.

### Data-quality auto-trim

mfapi.in occasionally serves history that combines pre- and post-scheme-merger NAVs without rebasement. For example, scheme `140196` (Edelweiss Liquid) has a `+9903.59%` one-day "jump" on 2017-07-01 because the post-July-2017 NAV is in different units than the pre-July-2017 NAV (likely from a scheme restructuring). Without correction, the since-inception CAGR for that fund computes to ~72%, which is nonsense for a liquid fund.

The CLI auto-detects any day-over-day jump exceeding 50% and treats the post-jump date as the effective inception. The detected event is preserved in the `data_quality.discontinuities_detected` array of the output JSON, so you can always see what was trimmed and why. The 50% threshold is well outside any plausible market move (even a 1:5 stock-style split would be +400%, far beyond anything mutual fund NAVs can do legitimately).

---

## Per-fund vs-benchmark comparison and rolling-return charts

For funds where you've configured a benchmark in `config/benchmarks.yaml`, `returns_main.py` automatically attaches an extra `vs_benchmark` block to the per-fund JSON, and `plot_main.py` produces a 3-panel PNG visualizing it. Two things make the comparison fair:

- The fund's own metric machinery (`mfhelper.returns_calc`) is reused on the index history, so trailing returns and rolling-CAGR distributions for the benchmark are computed by exactly the same code paths as the fund's. No quirky-different-conventions gotcha.
- Active returns (fund − benchmark) are paired per window: same start date, same end date, same elapsed-years denominator. This is what makes "fund beat benchmark in 96% of 3-year windows" a defensible statement instead of a comparison of two independently-computed numbers.

### Configuring benchmarks

```yaml
# config/benchmarks.yaml
benchmarks:
  - code: "120492"
    fund_name: "JM Flexicap Fund (Direct) - Growth Option"
    index_name: "NIFTY 500"
    variant: "PR"
    note: "Optional free-form annotation surfaced into vs_benchmark.data_quality"
```

`index_name` must match the niftyindices.com historical-data dropdown spelling exactly (case-sensitive). Common values: `NIFTY 50`, `NIFTY 100`, `NIFTY 200`, `NIFTY 500`, `NIFTY MIDCAP 150`, `NIFTY SMALLCAP 250`.

### Running

```bash
.venv/bin/python returns_main.py --code 120492          # JSON now includes vs_benchmark
.venv/bin/python plot_main.py    --code 120492          # PNG to data/fund_plots/120492.png
.venv/bin/python plot_main.py    --no-benchmark         # skip the overlay even if mapped
.venv/bin/python plot_main.py    --refresh-benchmark    # bypass the local cache
```

Benchmark history is fetched once from niftyindices.com and cached at `data/benchmark_history/<index>_<variant>.json` for `~18` hours, so repeat runs are fast even across multiple funds.

### What's in `vs_benchmark`

| Sub-section | What it tells you |
|---|---|
| `trailing_returns` | Benchmark's own 1D/1W/.../since-inception, computed by the same code as the fund's (apples to apples) |
| `rolling_returns` | Benchmark's 1Y/3Y/5Y/7Y rolling-CAGR distributions |
| `trailing_active_returns` | Fund minus benchmark, per trailing window. Sub-1Y is absolute-return delta; multi-year is CAGR delta |
| `rolling_active_returns` | Distribution of fund − benchmark CAGR pairs over rolling windows; includes `pct_fund_beat_benchmark`, `pct_fund_beat_by_3` (alpha > +3%/yr), and `pct_fund_underperformed_by_3` |
| `beat_rate_pct` | Quick-glance: % of N-year windows in which the fund's CAGR exceeded the benchmark's |
| `information_ratio_3y` / `information_ratio_5y` | Active CAGR ÷ tracking error (annualized SD of daily fund-vs-benchmark log-return delta). The standard "skill per unit of deviation" measure |
| `data_quality.note` | If we used PR (price-return) data — which is what niftyindices.com's public endpoint exposes — this note flags that the fund's apparent outperformance is overstated by the index dividend yield (~1-1.5%/yr for NIFTY equity indices) compared to the strictly-fair TRI comparison every AMC factsheet uses. The *shape* of the rolling distribution is unaffected |

### Plot layout

`plot_main.py` produces a single PNG per fund (`data/fund_plots/{code}.png`) with three stacked panels:

1. **Top — rolling 3Y CAGR over time.** x = window start date; y = annualized return for the 3Y window starting that day. Benchmark same-window CAGR overlaid as a dashed line. The 12% rule-of-thumb is drawn as a horizontal reference.
2. **Middle — four side-by-side histograms** (one per window: 1Y / 3Y / 5Y / 7Y) showing the SHAPE of rolling-CAGR distributions. Benchmark distribution overlaid translucent in a contrasting color. Histogram x-limits are clipped to the central 99% so COVID-era extremes don't squash the bulk of the distribution into invisible bins.
3. **Bottom — paired box plots** comparing all four window lengths side by side. Shows how spread tightens as the window grows.

Plots and benchmark caches are git-ignored by default (`data/fund_plots/`, `data/benchmark_history/`).

---

## Uninstall / disable the scheduler

```bash
launchctl unload ~/Library/LaunchAgents/com.mfhelper.daily.plist
rm ~/Library/LaunchAgents/com.mfhelper.daily.plist
```

The project files stay; only the scheduled trigger is removed.

---

## Changing the schedule time

Edit the `StartCalendarInterval` block in `scripts/com.mfhelper.daily.plist` (change `Hour` and `Minute`), then re-run `./scripts/install_launchd.sh`.
