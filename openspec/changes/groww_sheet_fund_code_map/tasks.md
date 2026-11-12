# Tasks: Google Sheets fund-code map

- [x] Approve the design decisions in `design.md`.
- [x] Add the `Fund Code Map` tab to the selected Google Sheet and seed the supplied 13 fund name/code pairs.
- [x] Read and validate the map tab from Vercel for each Groww import.
- [x] Use a unique normalized map match before the existing MFAPI fallback.
- [x] Remove the requirement for `MFHELPER_FUND_CODE_MAP` after deployment.
- [x] Preserve `Current Holdings` when the map tab cannot be read or validated.
- [ ] Add synthetic tests for valid, missing, malformed, duplicate, and updated map rows.
- [ ] Verify using a throwaway sheet or development credentials; do not modify production data during tests.
- [ ] Run `pytest tests/`.
