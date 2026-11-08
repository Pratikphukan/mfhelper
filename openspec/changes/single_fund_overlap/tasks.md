# Tasks: Compare one fund with the configured funds

- [x] User selects AMFI scheme code and excludes funds marked `active: false`.
- [x] User clarifies that the target AMFI code may be outside the configured comparison list; YAML contains comparison funds.
- [x] User approves target lookup behavior, including an explicitly selected target marked inactive in the YAML.
- [x] User approves the complete design in `design.md`.
- [x] Implement the focused CLI using existing overlap helpers.
- [x] Add unit tests for target selection, active/inactive scope, ranking, and missing holdings.
- [x] Update README with an example command and explain the overlap percentage.
- [x] Verify the CLI help and unit tests; no sheet was written.
- [x] Run `pytest tests/` and confirm all tests pass (413 passed).
