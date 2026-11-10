# Tasks: Groww Current Holdings

- [x] Confirm the tab schema, daily-alert data source, and replace-current-state behavior.
- [x] Read the minimal `MFHELPER_FUND_CODE_MAP` Vercel Secret containing only fund names and AMFI codes.
- [x] Document Vercel setup for the Google Sheets credential and fund-code mapping Secret.
- [x] Add safe parsing and validation for Groww XLSX exports.
- [x] Match holdings via the private mapping first, then use MFAPI for one exact Direct Growth match; retain unmatched rows without guessing.
- [x] Refresh the `Current Holdings` tab only after the complete export validates.
- [x] Preserve existing sheet contents if parsing, validation, or the sheet update fails.
- [x] Make the latest imported holdings available to the daily alert and surface the statement date.
- [x] Ensure uploaded XLSX files are discarded on success and failure.
- [x] Add tests using synthetic Groww workbooks without touching production Sheets or live state.
- [x] Cover exact, ambiguous, unmatched, API failure, and cached AMFI scheme-code lookups.
- [x] Run the project test suite after implementation approval.
- [ ] Verify the MFAPI-backed import and daily `--dev` workflow with development credentials and a throwaway sheet; do not touch production Sheets or live state.
