# Design: Groww Current Holdings

## Goal

Let the user explicitly upload a new Groww XLSX statement through the existing remote import page. Refresh a dedicated current-holdings tab and make the latest uploaded holdings available to the daily alert. The import does not run as part of Daily NAV.

## Proposed Flow

1. The user selects a Groww XLSX export on the existing remote import page.
2. MFHelper validates the workbook, reads the statement date, and parses the complete holdings table.
3. MFHelper checks that all required fields and rows are valid before changing the current table.
4. MFHelper replaces the contents of the dedicated `Current Holdings` tab with the parsed holdings and one `Last Updated` timestamp for the import.
5. The daily alert reads the latest holdings from this same Google Sheets tab and can show the statement date so the user can see how recent it is.
6. The uploaded workbook is discarded after the request, on success or failure.

## Sheet Shape

Use a separate `Current Holdings` tab so the Groww upload does not overwrite the source export or other manually maintained tabs. The tab should follow the Groww table, with these columns:

| Column | Purpose |
| --- | --- |
| Scheme Name | Fund name from the export |
| AMFI Scheme Code | Exact AMFI code when one unique scheme match is found |
| Category | Groww category |
| Sub-category | Groww sub-category |
| Folio No. | Distinguishes holdings in separate folios |
| Units | Units currently held |
| Invested Value | Amount invested as reported by Groww |
| Current Value | Current holding value as reported by Groww |
| Returns | Return amount as reported by Groww |
| XIRR | Fund/folio XIRR as reported by Groww, if present |
| Statement Date | Date shown as `Holdings As On` in the export |
| Last Updated | Timestamp when MFHelper successfully imported the export |

The `Statement Date` and `Last Updated` have different meanings: the first is the date the holdings values represent; the second is when MFHelper processed that file. `Last Updated` is repeated on each row so the data remains a normal rectangular table for filtering and analysis.

## AMFI Scheme Code Matching

- Match the detailed Groww scheme name and fund house against the AMFI scheme catalogue, including plan and option details such as Direct Growth.
- Populate the code only when one unique matching scheme is found.
- If there is no match or more than one possible match, keep the holding and leave the code blank; show a review status for that row.
- An unresolved code must not reject the upload or be inferred from a similar fund name.
- Matching does not depend on the fund being active in `funds.yaml`; inactive or unconfigured holdings still belong in the user's current-holdings view.

## Refresh Behavior

- A successful upload replaces all holdings rows in `Current Holdings` with the new statement's rows.
- Holdings missing from the new file are removed from this current-state tab.
- The same statement uploaded again refreshes the table and timestamp; no duplicate rows accumulate.
- No prior snapshot is retained. Historical comparisons are out of scope for this version.
- Validate the entire workbook before replacing the current table. If parsing or validation fails, preserve the last good sheet contents.

## Daily Alert Data

The Google Sheets `Current Holdings` tab is the single current-state source for the user-facing sheet and daily workflow. The remote Vercel importer needs permission to update this spreadsheet, and the daily GitHub Actions workflow can read it using its existing Google Sheets access. This avoids maintaining a second latest-snapshot copy in Vercel Blob.

The alert should use only the latest successful statement. It can compare triggered funds with the user's current fund values and, when underlying holdings are available, show overlap or concentration context. It must display or report the statement date so stale data is visible. Because uploads are on demand, it cannot know about transactions made after that statement until a new file is uploaded.

## Privacy and Failure Behavior

- Parse only the detailed fund-and-folio holdings table.
- Ignore the personal-details section and Groww's overall holdings summary; do not store or use either.
- Do not retain the uploaded XLSX after processing.
- Do not change the sheet until workbook validation succeeds.
- Keep a failed import from clearing or partially replacing the last good snapshot.
- Use a development-only sheet or isolated fixture for verification; do not test against the live sheet.

## Questions for Approval

1. Approve giving the Vercel importer Google Sheets credentials so it can write the `Current Holdings` tab. The sheet remains the single current-state source; no holdings copy is kept in Vercel Blob.
2. Confirm the proposed `Current Holdings` columns, including AMFI Scheme Code, XIRR, and folio number.
3. Confirm that each successful upload replaces the whole table and no history is retained.
