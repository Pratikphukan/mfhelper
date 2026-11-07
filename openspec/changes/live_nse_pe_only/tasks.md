# Tasks: Use only live NSE P/E data

- [x] User confirms live-only P/E applies to the sheet and future advice.
- [x] Update P/E resolution to return unknown when a valid live NSE value is unavailable.
- [x] Update sheet source/state labels for unavailable P/E.
- [x] Update configuration, README, and example config to remove cache/manual fallback behavior.
- [x] Update existing tests for live-only behavior.
- [ ] Verify in `--dev` mode without touching production sheets or live state.
- [ ] Run `pytest tests/` and confirm all tests pass.
