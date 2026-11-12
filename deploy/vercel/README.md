# Private holdings import on Vercel

This deploys MFHelper's user-triggered import page in your Vercel account. The page supports CDSL CAS PDFs and Groww XLSX exports.

| Service | Folder | Job |
|---|---|---|
| `web` (Python / FastAPI) | `deploy/vercel/web` | GitHub sign-in, upload tickets, parsing, and Google Sheets updates |
| `upload_token` (Node) | `deploy/vercel/upload-token` | Checks a one-use ticket and creates a private, temporary Blob upload URL |

Vercel Services is a Beta feature. Routes are defined in the repository's `vercel.json`.

## Groww upload flow

1. Sign in with the GitHub account allowed by `GITHUB_ALLOWED_LOGIN`.
2. Select a Groww XLSX export on the import page.
3. The browser uploads it directly to a private Vercel Blob path named `tmp/<random>.xlsx`.
4. Python reads the detailed holdings table, ignores personal details and the overall summary, reads the `Fund Code Map` tab, then replaces the `Current Holdings` tab in Google Sheets.
5. The temporary XLSX is deleted after processing, whether import succeeds or fails.

The sheet contains one current row per fund and folio. It includes the Groww fund, category, folio, units, invested/current values, returns and XIRR, plus AMFI code, statement date and MFHelper's `Last Updated` timestamp. It omits AMC, Source, personal details and Groww's summary. Each successful upload replaces the previous rows; MFHelper keeps no upload history.

AMFI scheme codes are matched first by exact normalized name against the private `Fund Code Map` tab. If that does not give one code, MFHelper searches MFAPI by the full scheme name and accepts only one exact Direct Growth result. MFAPI wording may include harmless `Plan` or `Option` words. It rejects Regular, IDCW, and dividend options. Results are cached for 24 hours per warm service instance. If MFAPI is unavailable, no exact candidate is found, or multiple codes match, the code stays blank and the row is marked for review; the upload continues.

The private `Fund Code Map` tab must have `Scheme Name` and `AMFI Scheme Code` in cells A1 and B1. Add one scheme and AMFI code per row. Blank rows are ignored; any nonblank row with a missing name or invalid code stops the import and preserves the previous `Current Holdings` data. Conflicting duplicate names are treated as ambiguous and sent to the MFAPI fallback. MFAPI is a secondary lookup source and should not be treated as the source of truth for ambiguous matches.

The Daily NAV GitHub Action can read `Current Holdings` with its existing Google Sheets credentials and show the reported holding value/share and statement date alongside triggered alerts. This context does not change signal thresholds or investment suggestions. Transactions after the statement date are not reflected until another upload.

## Configuration

1. Create a Vercel project from your repository. Select the **Services** framework preset if asked.
2. Create and connect a **private** Blob store to the project. The connection adds Vercel's Blob access settings. Do not add a public read-write token.
3. Create a GitHub OAuth App for sign-in. Set Homepage URL to `https://<project>.vercel.app` and callback URL to `https://<project>.vercel.app/oauth/callback`. MFHelper requests only `read:user` and allows only the configured GitHub login.
4. Create a Google Cloud service account with Google Sheets API access. Share the target spreadsheet with its `client_email` as an Editor. Add these Vercel Production environment variables:

   | Variable | Value |
   |---|---|
   | `MFHELPER_PUBLIC_URL` | `https://<project>.vercel.app` (HTTPS, no path) |
   | `MFHELPER_SESSION_SECRET` | Random secret, at least 32 characters |
   | `MFHELPER_TICKET_SECRET` | A different random secret, at least 32 characters; set for both services |
   | `GITHUB_OAUTH_CLIENT_ID` | Client ID from your OAuth App |
   | `GITHUB_OAUTH_CLIENT_SECRET` | Client secret from your OAuth App |
   | `GITHUB_ALLOWED_LOGIN` | Your GitHub login |
   | `MFHELPER_SPREADSHEET_ID` | The ID from your Google Sheets URL |
   | `MFHELPER_GOOGLE_SERVICE_ACCOUNT_JSON` | The full service-account JSON, stored as a secret |

   Generate random secrets with `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`. Keep the service-account JSON private. The fund mapping stays in the private Google Sheet and no longer needs a Vercel environment variable.
5. Deploy the project. The web build runs `vendor.py`; its output should say `vendored 8 mfhelper modules`.
6. Open the Production URL, sign in, and upload a Groww XLSX. If `Current Holdings` does not exist, the first successful import creates it. A tab with a different header layout is left unchanged and needs manual review.

The XLSX is processed by Vercel and is not saved in the repository. Vercel handles it temporarily during upload and parsing. Do not enable request-body logging or third-party log drains for this project.

## Failure behavior

- The importer validates the whole workbook before writing to Sheets.
- A parse or Sheets error leaves the previous table contents in place.
- A successful replacement clears rows left over from a larger previous upload.
- A temporary upload abandoned before processing is removed during a later request once it is older than 15 minutes.
- The Daily NAV workflow reads `Current Holdings`; with `--dev`, it looks for `Current Holdings (Dev)` to avoid the production snapshot.

## Local checks

```bash
pytest tests/                                        # Synthetic tests; no live Google Sheet writes
cd deploy/vercel/upload-token && npm ci && npm test  # Node ticket and presign tests
```

For manual workflow verification, use `--dev` and a development sheet. Do not test imports against the production spreadsheet.
