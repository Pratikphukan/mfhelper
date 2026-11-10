# Tasks: Groww Current Holdings

- [x] Confirm the tab schema, daily-alert data source, and replace-current-state behavior.
- [ ] Read the minimal `MFHELPER_FUND_CODE_MAP` Vercel Secret containing only fund names and AMFI codes.
- [ ] Document Vercel setup for the Google Sheets credential and fund-code mapping Secret.
- [ ] Add safe parsing and validation for Groww XLSX exports.
- [ ] Match holdings to AMFI Scheme Codes only when the scheme name and fund house resolve uniquely; retain unmatched rows without guessing.
- [ ] Refresh the `Current Holdings` tab only after the complete export validates.
- [ ] Preserve existing sheet contents if parsing, validation, or the sheet update fails.
- [ ] Make the latest imported holdings available to the daily alert and surface the statement date.
- [ ] Ensure uploaded XLSX files are discarded on success and failure.
- [ ] Add tests using synthetic Groww workbooks without touching production Sheets or live state.
- [ ] Cover exact, ambiguous, and unmatched AMFI scheme-code lookups.
- [ ] Verify with the `--dev` path and confirm the daily NAV workflow is unaffected.
- [ ] Run the project test suite after implementation approval.
