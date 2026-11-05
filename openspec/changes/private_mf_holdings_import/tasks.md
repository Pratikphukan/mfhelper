# Tasks: Private Mutual-Fund Holdings Import

- [x] Identify CDSL CAS from the user's inbox and confirm CDSL's PAN-uppercase PDF password rule.
- [x] Choose a file-picker import page in a per-user GitHub Codespace.
- [x] Choose remote processing in the user's Codespace and persistent snapshot storage in their private repository.
- [x] Use statement values only; defer latest-NAV estimates.
- [x] Store the snapshot as a normal file in the user's private repository, relying on repository access controls.
- [x] Configure a private Codespaces port and verify repository privacy before accepting uploads.
- [x] Inspect the original CDSL CAS in the browser and identify its reporting-period end and holdings columns (`Closing Balance (Units)`, `Valuation`).
- [ ] Run an end-to-end import of the encrypted original in the private Codespace and verify the extracted snapshot against the statement.
- [x] Build the private upload page and Codespace processing flow.
- [x] Parse and validate fund identity, units, statement values, and statement date; fail safely when required fields are missing.
- [x] Use the CDSL statement period end as the holdings date; prefer labeled portfolio/statement dates over generic NAV dates and cover precedence with regression tests.
- [x] Prompt for PAN in the import page and avoid persisting or logging it.
- [x] Save only the minimal holdings snapshot in that user's private repository; close and discard the uploaded file after processing.
- [x] Make updates atomic and repeated imports idempotent; preserve the previous snapshot on parse/commit failure.
- [x] Keep the holdings cache out of the daily workflow and public Pages output in this first phase.
- [x] Verify date selection and holdings-column extraction with synthetic fixtures without touching production Google Sheets or live state.
- [x] Install Codespaces importer dependencies in the GitHub Actions test workflow.
