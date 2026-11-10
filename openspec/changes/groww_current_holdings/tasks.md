# Tasks: Groww Current Holdings

- [ ] Confirm the tab schema, daily-alert data source, and replace-current-state behavior.
- [ ] Add safe parsing and validation for Groww XLSX exports.
- [ ] Refresh the `Current Holdings` tab only after the complete export validates.
- [ ] Preserve existing sheet contents if parsing, validation, or the sheet update fails.
- [ ] Make the latest imported holdings available to the daily alert and surface the statement date.
- [ ] Ensure uploaded XLSX files are discarded on success and failure.
- [ ] Add tests using synthetic Groww workbooks without touching production Sheets or live state.
- [ ] Verify with the `--dev` path and confirm the daily NAV workflow is unaffected.
- [ ] Run the project test suite after implementation approval.
