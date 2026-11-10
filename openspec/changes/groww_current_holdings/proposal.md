# Groww Current Holdings

## Problem

MFHelper can receive a Groww mutual-fund holdings export, but the user needs a simple current-holdings view that can inform daily alerts. A historical log is not needed for the first version, and Groww exports arrive only when the user chooses to upload one.

## Proposal

Add an on-demand upload through the existing remote import page. MFHelper reads a selected Groww XLSX export and refreshes a dedicated `Current Holdings` Google Sheets tab with the newest holdings. The tab should resemble Groww's holdings table, include an AMFI Scheme Code when there is one clear match, and include a `Last Updated` timestamp showing when MFHelper processed the file. It should also preserve the report's statement date (`Holdings As On`).

Each successful import replaces the current table with the new holdings. Holdings absent from the newest statement are removed from this current view. No historical snapshots are retained. The daily alert can use the latest uploaded snapshot and should be clear about its statement date.

AMFI codes are resolved first from a minimal private mapping in Vercel (`MFHELPER_FUND_CODE_MAP`), with an automated search fallback to `mfapi.in` filtering for unique Direct Growth plans. An unmatched or ambiguous holding remains in the sheet with a blank code and a review status; MFHelper must not guess a code or reject the complete import.

The original XLSX is temporary input and is discarded after processing. MFHelper reads only the detailed fund-and-folio holdings rows. It ignores the personal-details section and Groww's overall holdings summary, and does not copy either into MFHelper.

## Out of Scope

- Scheduled or automatic Groww imports.
- Historical snapshots or comparisons between past statements.
- Changes to the Daily NAV worksheet or run schedule.
- Investment recommendations or automatic trades.
