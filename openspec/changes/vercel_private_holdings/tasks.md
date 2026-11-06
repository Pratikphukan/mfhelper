# Tasks: Per-user Vercel Holdings Import

## Design gate

- [x] User answers Decisions 1-6 (1B temp Blob, 2A private Blob, 3A FastAPI, 4A GitHub OAuth, 5A remove OCI, 6A default domain).
- [x] User accepts the relaxed PDF-retention rule (temp private Blob, deleted on all paths).
- [x] Verified in Vercel docs: private Blob, overwrite, function duration/memory, Python bundle size. Result: Python SDK has no client-upload support, which blocked 1B + 3A as written.
- [x] User chose R1 (hybrid Python + Node token service).
- [x] Verified Vercel Services (Beta) supports Python + Node in one project.
- [x] User signed off R1 details: Services Beta, signed-ticket trust model, opportunistic orphan cleanup, OIDC credentials.
- [x] Verified `issueSignedToken` + `presignUrl` exist in `@vercel/blob` and support private PUT with content-type/size limits (simplification of `handleUploadPresigned`).

## Implementation

- [x] `mfhelper/upload_ticket.py`: HMAC-signed 120 s ticket (audience, login, nonce, 25 MB limit).
- [x] `deploy/vercel/upload-token/`: Node service (`ticket.js`, `presign.js`, `index.js`) that verifies the ticket and returns a presigned private PUT URL for a server-chosen `tmp/<uuid>.pdf`.
- [x] `mfhelper/vercel_holdings_cache.py`: private Blob adapter (temp PDF read/delete, stale cleanup, single `holdings/current.json` with older-statement and idempotency guards).
- [x] `mfhelper/vercel_holdings_import_app.py`: GitHub OAuth allowlist, CSRF, `/upload-ticket`, `/import`, nonce CSP, no third-party scripts.
- [x] `vercel.json`, `deploy/vercel/web/` (entrypoint, light `requirements.txt`, `vendor.py`), `.gitignore`.
- [x] Python tests (ticket incl. Python-to-Node cross check, storage, app incl. real synthetic encrypted PDF, packaging) and Node tests.
- [x] CI runs Node tests and installs `httpx` so the app tests are not skipped.
- [x] `deploy/vercel/README.md`, root `README.md` section, `scripts/make_synthetic_cas.py`.
- [x] `pytest tests/`: 198 passed. `npm test`: 12 passed, 1 skipped (cross-language case, run by pytest).
- [x] Shared snapshot logic is reused from `holdings_cache.py`; no further extraction needed because the OCI copy is removed below.

## Still to do (needs your Vercel account)

- [ ] Deploy to a **throwaway** Vercel project with its own private Blob store and OAuth app; confirm the build log shows `vendored 6 mfhelper modules` (verifies `buildCommand` + packaging for the Python service in Services mode).
- [ ] Import `scripts/make_synthetic_cas.py` output end to end; confirm `holdings/current.json` exists, `tmp/` is empty afterwards, and the store rejects unauthenticated reads.
- [ ] Confirm the presigned PUT works against a private store from the browser (CORS/CSP) and that a 25 MB PDF stays inside function time/memory limits.
- [ ] Verify one real import in your own project before relying on the stored snapshot.
- [ ] After that import succeeds: remove `mfhelper/oci_holdings_cache.py`, `mfhelper/oci_holdings_import_app.py`, `deploy/oci-vm/`, `requirements-oci.txt`, OCI tests, and the OCI README section (Decision 5A).
