# Tasks: Portfolio-weighted holdings overlap

- [x] Review and approve the design and open decisions.
- [x] Read `Current Holdings` and `Fund Code Map` from Google Sheets; stop safely on invalid or unavailable source data.
- [x] Aggregate folios by AMFI code and calculate mapped/fetched coverage.
- [x] Calculate portfolio-weighted stock exposures from fund values and underlying allocations.
- [x] Preserve the pairwise matrix and detailed fund-pair breakdown in the agreed report layout.
- [x] Add `--dev` input/output tab support.
- [x] Add synthetic unit tests for grouping, weighted exposures, missing mappings, failed fetches, stale dates, and safe sheet writes.
- [x] Verify using fake clients only; do not touch production sheet data during tests.
- [x] Run `pytest tests/` and verify all tests pass.
