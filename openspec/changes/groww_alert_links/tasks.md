# Tasks: Use Fund Code Map Groww URLs in alerts

- [x] Review and approve the design and fallback behavior.
- [x] Read and validate the `Groww URL` column from `Fund Code Map` in the daily alert job.
- [x] Match valid links to funds by AMFI scheme code.
- [x] Use fund links in confluence and trim email cards; remove the obsolete generated search URL.
- [x] Add synthetic parser, lookup, and email-rendering tests.
- [x] Verify with fake Sheets clients and no production writes.
- [x] Run `pytest tests/` and verify all tests pass (493 passed).
