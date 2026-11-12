# Read the Groww fund-code map from Google Sheets

## Problem

`MFHELPER_FUND_CODE_MAP` is stored in Vercel environment variables. When the user's private `funds.yaml` changes, keeping the environment value in sync requires editing Vercel and redeploying. The existing MFAPI fallback can resolve many new schemes, but it does not replace the user's preferred exact mapping.

## Proposal

Move the private fund-name-to-AMFI-code mapping into the `Fund Code Map` tab in the user's existing Google Sheet. The tab has been created with the two headers and the 13 `name`/`code` pairs supplied from `funds.yaml`, including funds marked inactive, because inactive funds can still appear in current holdings.

At each Groww import, Vercel reads this tab using the existing Google service account and uses its mapping before the existing MFAPI fallback. The user can add or correct map rows in the spreadsheet without editing a Vercel environment variable or redeploying.

## Out of Scope

- Storing `funds.yaml` itself in the spreadsheet.
- Making the sheet public or adding fund-map editing to the web page.
- Changing the MFAPI fallback rules.
