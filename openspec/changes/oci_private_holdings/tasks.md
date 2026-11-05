# Tasks: Per-user OCI Holdings Import

- [x] Confirm OCI Compute VM as the worker runtime, GitHub OAuth for sign-in, and latest-snapshot-only retention.
- [x] Confirm a stable public VM IP with automated short-lived IP certificate renewal for HTTPS and GitHub OAuth.
- [x] Document single-user OCI resource setup, bucket-scoped IAM, private bucket, HTTPS ingress, and IP certificate renewal.
- [x] Build the authenticated import page and VM service templates so it can run from the public MFHelper source without a private GitHub repository.
- [x] Require the allowlisted GitHub OAuth identity and verify private bucket/no-versioning before multipart upload parsing.
- [x] Decrypt and parse the CDSL CAS in request memory/private temp storage; close and delete upload/password on all paths.
- [x] Atomically replace only the validated latest holdings snapshot at `holdings/current.json`.
- [x] Document setup, access controls, certificate renewal, deployment updates, and data deletion.
- [x] Add synthetic parser/storage/auth tests and run them without production sheets or live state.
- [ ] Verify one end-to-end import in the user's OCI tenancy before relying on the stored snapshot.
