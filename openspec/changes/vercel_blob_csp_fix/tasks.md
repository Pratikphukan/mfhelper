# Tasks: Allow Vercel Blob Uploads Through CSP

- [x] Approve the path-scoped `connect-src` change for `https://vercel.com/api/blob/`.
- [x] Add the source to the import page's CSP without changing other directives.
- [x] Add a regression test for the generated CSP.
- [x] Run the repository tests without touching production holdings or live state (GitHub Actions passed).
- [ ] Redeploy and verify the synthetic upload reaches `/import` and cleans up the temporary PDF.
