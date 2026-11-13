# Design: Show the 200-day SMA slope in Market Regime

## Goal

Make the 20-session 200-day SMA slope check visible in the Market Regime sheet.

## Data Flow

1. Continue fetching the existing NIFTY 500 daily close history through `fetch_benchmark_history` and its local cache.
2. Calculate the current 200-day SMA and the 200-day SMA ending 20 trading sessions before the current index session, using the same close series and `slope_lookback_days` setting used by `classify_regime`.
3. Add the earlier 200-day SMA value and the difference (`current SMA - earlier SMA`) to `MarketContext` and write both to the `Market Regime` sheet.
4. Keep the BEAR classification comparison unchanged. The added value is for transparency only.
5. If there is not enough history to calculate the value, leave the sheet cell blank and preserve the existing unavailable-data behavior.

## Sheet Layout and Migration

Add `Long SMA (20 Sessions Ago)` and `200D SMA Change (20 Sessions)` beside the existing `Long SMA` column. A negative change means the 200-day SMA has fallen over the lookback period; a positive change means it has risen.

When the writer finds the known existing header, safely insert the two columns beside `Long SMA` and update the header. Preserve every existing value. Historical rows will have blank cells in the new columns; new or re-run daily rows will include both values. Continue rejecting unrelated or unknown headers without writing.

## Verification Safety

- Use synthetic benchmark closes and fake Sheets clients in tests.
- Do not write to production Google Sheets during verification.
- Run `pytest tests/` before completion.

## Open Decision

## Approved Decision

- Preserve existing rows when migrating the known Market Regime header. Leave the two new columns blank for past dates; future runs populate them.
