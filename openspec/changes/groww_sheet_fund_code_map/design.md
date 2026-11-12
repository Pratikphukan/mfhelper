# Design: Google Sheets fund-code map

## Goal

Make fund-to-AMFI-code edits available to the Groww importer without changing a Vercel environment variable or redeploying.

## Proposed Flow

1. The existing spreadsheet has a `Fund Code Map` tab with `Scheme Name` and `AMFI Scheme Code` columns. It is seeded with the 13 supplied funds, including entries marked inactive in `funds.yaml`.
2. For each Groww XLSX upload, Vercel reads `Fund Code Map` with the Google service account already used to update `Current Holdings`.
3. Read the two columns `Scheme Name` and `AMFI Scheme Code`; require those headers in row 1. Ignore fully blank rows. Reject a nonblank row if its name or code is missing, or if the code is not numeric. Accept codes stored as text or numbers. Build the normalized name-to-code map in memory; do not cache it between imports or store another copy in Vercel Blob or an environment variable.
4. For each distinct scheme in the uploaded statement, use a unique normalized exact match from the sheet. If there is no unique exact match, use the existing MFAPI Direct Growth lookup.
5. Write `Current Holdings` only after map loading/validation and the holding rows have been prepared.
6. The user can edit the sheet directly; the next upload sees those edits without a redeploy.

The existing name normalization is case-insensitive, Unicode-normalized, and treats punctuation or repeated separators as spaces. The existing MFAPI fallback and its 24-hour warm-instance cache remain unchanged.

## Failure Behavior

The importer must not clear or replace `Current Holdings` until the map has been read and validated. If the tab is missing/unreadable or any nonblank row is malformed, return a clear import error and preserve the last good `Current Holdings` data. If one normalized name has conflicting codes, mark that name ambiguous and let MFAPI try; if unresolved, keep the code blank with the existing review status.

## Privacy

The map remains in the user's private spreadsheet. Vercel uses the existing service account. The environment variable `MFHELPER_FUND_CODE_MAP` is no longer needed after the map tab has been seeded and the deployed code reads it.

## Agreed Design Decisions

1. **Environment variable migration:** Remove `MFHELPER_FUND_CODE_MAP` as a requirement and make the sheet the source of truth. This avoids maintaining two lists. A missing/unreadable sheet will stop the import safely.

2. **Map read or row validation failure:** If the tab is missing/unreadable or any nonblank row has a missing name or invalid code, stop the Groww import and leave `Current Holdings` untouched. Blank rows are ignored. This prevents a broken map from producing an unexpected update.

3. **Conflicting duplicate names:** If the same normalized name maps to different AMFI codes, mark that name ambiguous and let the existing MFAPI fallback try. If MFAPI cannot uniquely resolve it, write a blank code with the existing review status. This avoids blocking all holdings updates because of one conflicting name while avoiding an arbitrary code choice.

4. **Cell types:** Read codes as strings and validate that they contain only digits. Accept numeric cells as well, so ordinary Google Sheets number formatting does not invalidate the map.

## Approval Status

The user approved this design before implementation.
