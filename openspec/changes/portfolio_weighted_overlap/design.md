# Design: Portfolio-weighted holdings overlap

## Goal

Make the on-demand `Portfolio Overlap` report describe the user's actual reported positions and show the portfolio-level effect of overlapping underlying stocks.

## Proposed Data Flow

1. Read `Current Holdings` from the user's Google Sheet. This is the source of truth for which funds are currently owned, their folio rows, current values, and statement date. Do not use `config/funds.yaml` as the fund list.
2. Read `Fund Code Map` from the same spreadsheet. Use its `Scheme Name` and `AMFI Scheme Code` columns to resolve missing AMFI codes by unique normalized exact name. Existing valid codes in `Current Holdings` remain usable. Conflicting or missing mappings are reported, not guessed.
3. Group all position rows by AMFI code and sum their current values, so different folios of one scheme are treated as one fund position. Keep unmapped rows visible in the report and include their current value in the total portfolio denominator, but do not fetch constituents for them.
4. Use the existing AMFI-to-ISIN, Tickertape ID mapping, holdings fetch, and pairwise overlap calculations for funds with resolved codes. Keep the existing local Tickertape mapping cache.
5. For each fetched stock, estimate portfolio exposure as:

   `fund current value / total reported current value × stock allocation within fund`

   Sum the contributions for the same stock across funds. Show the estimated rupee exposure and percentage of the reported portfolio. Values represent the Groww statement date; they are not live valuations.
6. Write a combined report containing the statement date and age, total reported value, mapped/fetched coverage, unresolved or unavailable funds, largest underlying stock exposures, the pairwise matrix, and the existing detailed pairwise stock breakdown.
7. Add `--dev` behavior for safe verification: read `Current Holdings (Dev)` and write `Portfolio Overlap (Dev)`. Normal on-demand runs continue to use the production tabs.

## Exposure and Coverage Rules

- The portfolio denominator is the sum of all current values in `Current Holdings`, including rows with missing codes or failed constituent lookups. This avoids overstating the percentages among only the successfully mapped funds.
- Report mapped value and constituent-data coverage so the reader can see how much of the portfolio the exposure calculation actually covers.
- Do not treat missing constituent data as 0% overlap. List the affected funds and continue with a clearly labeled partial report, unless the required input tabs cannot be read or validated.
- Group positions by AMFI code before calculations; duplicate folios do not create duplicate fund entries in the matrix.
- Use the Groww statement date from `Current Holdings`. Tickertape's current holdings response does not currently expose a source as-of date through `fetch_fund_holdings`; show the local report fetch time and label constituent data as latest data returned by Tickertape, without claiming an underlying holdings date.

## Sheet Behavior

- Proposed default: keep one `Portfolio Overlap` tab and replace its contents on each successful run, with the portfolio-level summary first and the pairwise matrix/details below it.
- If the source tabs are missing, malformed, or unreadable, stop before clearing the existing report.
- The report remains on-demand; it is not added to the daily workflow.

## Open Decisions

## Approved Decisions

1. Keep one `Portfolio Overlap` tab. Put the portfolio summary and largest stock exposures first, followed by the existing matrix and details.
2. Write a partial report when some funds cannot be mapped or fetched. Show coverage and warnings. If either required source tab cannot be read or validated, preserve the previous report.
3. Show the statement date and age on every report. Label the statement stale after 30 days.

## Verification Safety

- Use synthetic holdings and fake Sheets/API clients for automated tests.
- Use `--dev` and development tabs for any manual verification; do not write production sheet data during testing.
- Run `pytest tests/` before completion.
