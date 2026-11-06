# Design: Per-user Vercel Holdings Import

**Status: Decisions 1-6 answered by the user. Awaiting explicit sign-off on the "Follow-up Design Points" section before any code is written.**

## Recorded Answers

| # | Decision | Choice |
|---|---|---|
| 1 | Body-size limit | **B.** Browser uploads to a temporary private Blob; the Function parses and deletes it |
| 2 | Snapshot store | **A.** Vercel Blob, private access |
| 3 | Runtime | **A.** FastAPI on Vercel's Python runtime |
| 4 | Authentication | **A.** GitHub OAuth allowlist only |
| 5 | OCI code | **A.** Remove after one successful Vercel import |
| 6 | Domain | **A.** Default `<project>.vercel.app` |

## Verification Results (Vercel docs, checked 2026-11-06)

- **User accepted** the relaxed PDF-retention rule (PDF may exist in a private Blob only between upload and parse; deleted on all paths).
- **Private Blob: supported.** Stores are private or public, fixed at creation. Private reads need authentication. Overwrite is supported (`allow_overwrite=True`), and the Python SDK offers `put_blob`, `get_blob`, `delete_blob`, and `head_blob`. Private blobs can be read with a consistent read from server code.
- **Function limits (Hobby):** 2 GB memory, 300 s max duration, 500 MB uncompressed Python bundle. These look sufficient for parsing a 25 MB PDF with `pdfplumber`, but real parse time and memory must be measured.
- **Request body limit confirmed:** 4.5 MB for Functions.
- **BLOCKER for Decision 1B + 3A.** The Vercel Blob **Python SDK does not support client uploads or client-token generation**. Docs: the Python SDK "doesn't currently support ... client uploads, Vercel Signed URLs ...". Browser-direct upload (the only way to bypass the 4.5 MB limit) needs the **JavaScript** SDK (`handleUpload` or `handleUploadPresigned`). So the Python-only FastAPI plan cannot issue upload tokens.
- `handleUpload` needs a long-lived `BLOB_READ_WRITE_TOKEN` and does not accept OIDC. `handleUploadPresigned` works with OIDC.

### Options to resolve the blocker (needs user decision)

- **R1. Hybrid project.** FastAPI (Python) for the OAuth session and parsing, plus one small Node function whose only job is to issue upload tokens. The Node function must trust the Python session, for example by verifying the same signed cookie with a shared secret, or by receiving a short-lived signed ticket minted by Python. Two runtimes and a shared-secret contract.
- **R2. Node does the auth and token step; Python only parses.** More Node code, GitHub OAuth done twice or moved to Node. Larger rewrite of the tested flow.
- **R3. Fall back to Decision 1A (direct upload, cap about 4 MB).** Pure Python, no Blob client-upload path and no temp PDF stored, so the retention-rule question disappears. Only works if the real CAS PDF is under about 4 MB.
- **R4. Fall back to Decision 1C (parse in browser).** PDF and PAN never leave the device. Needs a JS parser rewrite.

## Chosen resolution: R1 (hybrid Python + Node), proposed design for sign-off

**User chose R1.** The design below is a proposal; items marked **[CONFIRM]** need explicit approval.

### Platform support (verified)

Vercel **Services** (Beta, all plans) deploy several services in one project on one domain, routed by top-level `vercel.json` rewrites. Services are private unless a rewrite exposes them. `functions`, `buildCommand`, etc. move into each service. Risk: Services is Beta, so behaviour may change. **[CONFIRM] acceptable?**

### Layout

```text
vercel.json              services + rewrites
backend/                 FastAPI app (Python): OAuth, session, ticket, parse, Blob read/write/delete
  main.py                  entrypoint "main:app" (wraps the existing app logic)
upload-token/            Node service (JS): issues Blob client-upload tokens only
  index.js
mfhelper/                shared parser + snapshot rules (unchanged)
```

Rewrites (most specific first): `/upload-token/(.*)` -> Node service, `/(.*)` -> Python service. Same host, so the browser calls both without CORS.

### Trust between the two services: signed upload ticket

The Node service must not re-implement the Starlette session cookie. Instead:

1. Browser (signed in) calls `POST /upload-ticket` on Python with the CSRF `form_token`.
2. Python checks the session login is the allowlisted GitHub account, then returns a ticket: `base64url(payload).HMAC_SHA256(payload, MFHELPER_TICKET_SECRET)`, where payload = `{login, exp (now + 120 s), nonce, max_bytes: 26214400}`.
3. Browser calls the Node service to start the Blob upload, sending the ticket as `clientPayload`.
4. Node `onBeforeGenerateToken` verifies the HMAC and `exp`, then returns constraints: `allowedContentTypes: ["application/pdf"]`, `maximumSizeInBytes: 26214400`, short `validUntil`, `addRandomSuffix: true`, pathname forced to `tmp/<random>.pdf` (the browser-supplied name is ignored).
5. Node holds no session, no GitHub secret, and no parsing logic. `MFHELPER_TICKET_SECRET` is a new env var shared by both services, at least 32 random bytes. **[CONFIRM]**

Browser then uploads the PDF straight to Blob, calls `POST /import` on Python with `{blob_pathname, pan, form_token}`.

### Parse step (Python)

1. Enforce session + CSRF, as today, before doing any work.
2. Require `blob_pathname` to match `tmp/*.pdf` and reject anything else.
3. `head_blob` to check size is at most 25 MB before reading, then `get_blob(access="private")`.
4. `parse_cdsl_cas(pdf_bytes, pan)`.
5. `finally`: `delete_blob(temp)`, drop the bytes and PAN.
6. Apply the older-statement and idempotency guards using the stored `holdings/current.json`, then `put_blob("holdings/current.json", ..., access="private", allow_overwrite=True)`. Read the existing snapshot with a consistent read so guards see the latest.

### Orphan cleanup (proposed) **[CONFIRM]**

At the start of every `/import` and `/upload-ticket`, list `tmp/` and delete any temp blob older than 15 minutes. No Cron needed. Limitation: an abandoned upload stays until your next visit, up to a few days, as an encrypted PDF in your private store. It can be removed manually with `vercel blob` or the dashboard at any time.

### Blob credentials **[CONFIRM]**

- Python uses OIDC (`BLOB_STORE_ID` + `VERCEL_OIDC_TOKEN`), which is the Vercel default.
- Node needs either `handleUpload` with a long-lived `BLOB_READ_WRITE_TOKEN` (known to work; static secret in the Node service's env), or `handleUploadPresigned`, which works with OIDC and avoids a static token. **Recommend `handleUploadPresigned` if it supports private stores plus content-type and size limits; to be verified before implementation. Fall back to `handleUpload`.**

### Sign-off and refinements (2026-11-06)

User approved: Services Beta, signed-ticket trust model, opportunistic orphan cleanup, prefer OIDC/presigned credentials.

Refinement found while verifying the docs: instead of the `handleUploadPresigned` helper, the Node service uses the lower-level `issueSignedToken()` + `presignUrl()` pair and returns a ready presigned `PUT` URL scoped to one pathname, `application/pdf`, 25 MB, 5 minutes, `access: "private"`. Benefits: OIDC only (no `BLOB_READ_WRITE_TOKEN`), no Blob webhook / `onUploadCompleted`, and **no Vercel client library or third-party script in the browser**; the page does a plain `fetch(url, {method: "PUT", body: file})`. The page sends a strict CSP (nonce-based script, `connect-src` limited to self and `*.blob.vercel-storage.com`).

Known limitations accepted with this approach:
- The Python Blob SDK has no cache-bypass read. After an overwrite, `holdings/current.json` may be read stale for up to about 60 s. This only affects the older-statement/idempotency guard if two imports happen within a minute. The snapshot is stored with `cache_control_max_age=60` (the minimum).
- Tickets are not single-use; they expire after 120 s and only authorize one scoped PDF upload.
- The OCI code is **not** removed in this change set. Per Decision 5A it is removed after one successful Vercel import (tracked in `tasks.md`).
- Python packaging of the shared `mfhelper/` modules for the Vercel service root must be verified on a preview deployment (see `deploy/vercel/README.md`).

### Other decisions for this design

- Remove the `callback`/`onUploadCompleted` flow. The browser tells Python when to parse, so the Blob webhook is not needed.
- Remove the OCI bucket-privacy check. Replace with a startup check that the configured store is private (writing with `access="private"` to a public store fails because the access mode must match).
- Delete old temp blobs and the snapshot via a documented manual step; no deletion endpoint.
- The 25 MB cap is kept (client upload constraint and parse-time check).

### New environment variables

`GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET`, `GITHUB_ALLOWED_LOGIN`, `MFHELPER_SESSION_SECRET`, `MFHELPER_PUBLIC_URL` (existing); `MFHELPER_TICKET_SECRET` (new); `BLOB_STORE_ID` (+ OIDC, automatic); `BLOB_READ_WRITE_TOKEN` only if `handleUpload` is used.

## Follow-up Design Points (new, created by choices 1B + 2A)

Choice 1B means the PDF is briefly stored in Vercel Blob. This conflicts with the earlier "PDF never leaves request memory" rule, so the rule is relaxed to: **the PDF may exist in a private Blob only between upload and parse, and is deleted on every success and failure path.** Please confirm or adjust:

1. **Private Blob support.** The whole design assumes Blob supports private (token-only) access for both the temporary PDF and the snapshot. This must be verified against current Vercel docs first. If it is not available, choices 1B and 2A both fail and we revisit Decisions 1 and 2.
2. **Upload authorization.** The browser needs a short-lived upload token. The Function issues one only to the allowlisted GitHub session. It should be limited to `application/pdf`, 25 MB, and a server-chosen random path such as `tmp/<random>.pdf`.
3. **Parse trigger.** The browser, after upload completes, calls `POST /import` with the blob reference, the PAN, and the CSRF `form_token`. The PAN goes in this request body to the Function, never into Blob.
4. **Cleanup.** The Function deletes the temp blob in a `finally` block. Orphans can remain if the browser abandons the flow after upload or the Function crashes. Choose a cleanup approach: (a) delete any `tmp/` blob older than N minutes at the start of each import (no extra infrastructure, **proposed**), or (b) a Vercel Cron job, which needs a plan check.
5. **Pre-parse check.** Replace the OCI "bucket is private" check with a check that the Blob store is private, plus a size check on the uploaded blob before parsing.
6. **Overwrite semantics.** Blob overwrite of `holdings/current.json` needs explicit overwrite enabled. Confirm it replaces the object in place rather than creating a suffixed copy, so only the latest snapshot is kept.
7. **Reading the snapshot** (already required for the older-statement and idempotency guards) uses the server-side Blob token, never a public URL.
8. **Limits.** Confirm the function's max duration and memory are enough to parse a 25 MB PDF with `pdfplumber`. If not, the cap may need lowering.

## Reuse vs change (from the current OCI code)

| Area | Current (OCI) | Vercel plan |
|---|---|---|
| Parser | `casl_import.parse_cdsl_cas` | Unchanged |
| Snapshot shape / rules | `holdings_cache.snapshot_payload`, `_holdings_equal`, `_parse_iso_date` | Unchanged, reused |
| Auth | GitHub OAuth allowlist, signed session cookie, CSRF `form_token` | Unchanged logic; callback becomes the Vercel URL |
| App | `oci_holdings_import_app.py` (FastAPI + uvicorn) | Same FastAPI app exposed as a Vercel Function |
| Storage | `OCIHoldingsCache` (instance principal, bucket-privacy check) | New adapter, see Decision 2 |
| HTTPS | Reserved IP + Certbot short-lived IP cert | Provided by Vercel |
| Deploy | `deploy/oci-vm/*`, `requirements-oci.txt` | `vercel.json`, `api/` entrypoint, new requirements file |

## Open Decisions

### Decision 1: Handling the 4.5 MB request-body limit

Vercel Functions reject bodies above about 4.5 MB; today's limit is 25 MB.

- **A. Direct upload, lower the cap to about 4 MB.** Simplest and keeps the PDF inside one request. Risk: a large CAS (many years or many holdings) will be rejected. Need to check the size of your real statement.
- **B. Browser uploads to a temporary private Blob, then the Function parses and deletes it.** Supports 25 MB. The PDF is stored briefly in Vercel storage, which weakens "the PDF never leaves request memory". Needs a delete-on-all-paths guarantee and an orphan cleanup.
- **C. Parse in the browser (pdf.js/WASM) and send only extracted holdings.** The PDF and PAN never leave the device, which is best for privacy. It means rewriting the parser in JavaScript and diverging from the tested Python code.

### Decision 2: Snapshot store

- **A. Vercel Blob (private).** Closest to the OCI model: one object `holdings/current.json`, overwrite on success. Need to confirm at implementation time that the Blob store is created with private access and that reads need a token. If the store is only public-URL based, this option is unsafe.
- **B. Redis / KV from the Vercel Marketplace (for example Upstash).** Single key, simple atomic `SET`. Data is not reachable by URL. Adds a Marketplace integration and a free-tier limit.
- **C. Postgres from the Marketplace (for example Neon).** Overkill for one JSON document; only worth it if we later want history or multiple tables.
- **D. Keep the snapshot in a private GitHub repo via the Contents API.** No new Vercel storage, but needs a GitHub token with write scope and brings back Git history of old versions, which we removed on purpose.

### Decision 3: Runtime and framework

- **A. Keep FastAPI on Vercel's Python runtime.** Minimal change and the tests stay valid. Need to confirm bundle size with `pdfplumber` and `pypdf`, and cold-start time.
- **B. Rewrite as a Next.js app with a Python function only for parsing.** Nicer UI tooling, but larger rewrite and two runtimes. Not recommended for a single-page tool.

### Decision 4: Authentication layer

- **A. Keep GitHub OAuth allowlist (recommended).** Already implemented and tested; works with a stable Vercel hostname.
- **B. Vercel Deployment Protection / Vercel Authentication in addition.** Adds a second gate in front of the app; some protection modes depend on the plan.
- **C. Single shared secret passphrase.** Simpler but weaker; not recommended.

### Decision 5: Fate of the OCI implementation

- **A. Remove OCI code, `deploy/oci-vm/`, `requirements-oci.txt`, OCI tests, and README section after one successful Vercel import.**
- **B. Keep OCI as an alternative deployment target** behind a storage interface. More code to maintain.

### Decision 6: Domain

- **A. Default `<project>.vercel.app`.** The name is guessable, so the allowlist must be the real protection.
- **B. Custom domain.** You said earlier you have none; the default is sufficient.

## Data Handling (unchanged requirements)

- Authenticate the allowlisted GitHub login before parsing any multipart body.
- Keep the PDF and PAN only in request memory; drop them on every success and error path. Never log them or OAuth callback queries.
- Store only the existing minimal snapshot fields. No PAN, folio numbers, address, bank details, or original PDF.
- Replace the snapshot only after a valid parse, with the older-statement and idempotent-import guards.
- The snapshot must not be reachable through a public URL, build output, logs, or an unauthenticated endpoint.
- Secrets (`GITHUB_OAUTH_CLIENT_SECRET`, `MFHELPER_SESSION_SECRET`, store token) live only in Vercel environment variables, never in the repo.

## Risks to acknowledge

- Vercel becomes a third party that handles the PDF and PAN in transit. Disable or minimize request logging in the function and review log retention.
- Platform limits (body size, execution time, memory, bundle size) could change; verify against current Vercel docs when implementing.
- Vercel's free plan terms are for personal, non-commercial use.

## Testing Plan (after approval)

- Reuse the existing synthetic parser tests unchanged.
- Add storage-adapter tests with a fake client, mirroring `test_oci_holdings_cache.py`.
- Adapt app tests to the chosen entrypoint. Check: unauthenticated upload rejected before parsing, wrong GitHub login rejected, oversize rejected, CSRF token required.
- Dry-run with a synthetic encrypted PDF against a Vercel preview deployment and a throwaway store. Never use the real statement or production data during development.
