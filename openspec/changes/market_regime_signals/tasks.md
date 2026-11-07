# Tasks: Market Regime-Aware Signals

## Design gate (blocking)

- [x] Review current alert code, config, and benchmark fetching.
- [x] Check data availability (VIX and NIFTY 500 via yfinance; P/E via NSE; 10Y via FRED monthly) and measure regime band coverage on 5 years of data.
- [x] User answers D1-D9 (recorded in `design.md`).
- [x] User signs off the four "Consequences to confirm" items in `design.md` (all-funds scope, NSE/manual fallback, trimming never suppressed, valuation modifiers).
- [ ] If NSE P/E is chosen, verify access from GitHub Actions (NSE answered from a local machine on 2026-11-06; GitHub's cloud IPs are untested, so the manual `nifty50_pe` fallback is documented).

## Implementation (only after approval; subject to chosen options)

- [x] `mfhelper/market_regime.py`: fetch and cache NIFTY 500, India VIX, valuation; `classify_raw()`; `MarketContext`.
- [x] Smoothing/confirmation per D2. Implemented as a stateless replay of the last 60 sessions, so no regime state file exists.
- [x] `mfhelper/regime_filter.py` (`apply_regime_to_buys`, `check_trimming_for_context`) per D4-D7; config dataclass and `alerts_example.yaml` `regime:` section (disabled by default).
- [x] Wire into `main.py` before `dispatch_alerts_email`; add regime banner and suppressed section to the email.
- [ ] Optional: MCP `get_market_regime` tool (per D9).
- [x] Unit tests: boundaries, precedence, gaps, smoothing, scope (D3), missing data, byte-identical output when disabled.
- [x] Run with `--dev` (wiring tests fake every external system; `regime_main.py` is read-only); run `pytest tests/` and confirm all pass.
- [x] Regime coverage report on historical data (`python regime_main.py --history N`).
- [x] Update `daily_nav.yml` if new cache files or secrets are needed.
- [x] README and `alerts_example.yaml` documentation.

## Amendment 1 (advise, never mute) - approved and implemented

- [x] User approves Amendment 1 in `design.md`.
- [x] Remove suppression from `regime_filter.py`; add label text to buy signals and single-indicator rows.
- [x] Remove confirmation (`confirm_days`, replay) from `market_regime.py`, `config.py`, example config, README, CLI.
- [x] Remove the "Suppressed by market regime" email section and the only-suppressed skip rule.
- [x] Tests: "feature on never removes an alert" in every regime (unit grid and `main.run` wiring); labels; updated affected tests.
- [x] Quiet-day question: answered by Amendment 2 (the sheet row is written daily with no email). No daily email.

## Amendment 2 (record to a "Market Regime" tab) and Amendment 3 (record first, alerts later) - approved and implemented

- [x] User approves Amendments 2 and 3 in `design.md`.
- [x] `RegimeSettings.record_to_sheet` + `sheet_name` (both independent of `enable`) + validation + example config + README.
- [x] `mfhelper/regime_sheet.py`: `RegimeSheetWriter` (create tab/header, header-mismatch guard, replace same-day row, formats, retry, grow rows).
- [x] Wire into `main.py` after the NAV row is written; "(Dev)" tab under `--dev`; failures are warnings only.
- [x] Tests with a fake worksheet: create, append, same-day replace, header mismatch refusal, unavailable-data row, grow, retry; `main.run` wiring for record-only, advice-only, both, off, failing writer.
- [x] `pytest tests/` passes. No real sheet was written (fakes only).
- [ ] User: turn on `regime.record_to_sheet: true` in the `ALERTS_YAML` secret (and a manual `nifty50_pe` fallback), run once with `--dev` to see the "Market Regime (Dev)" tab, then let it run for about a month.
- [ ] After a month: review the tab and decide whether to turn on `regime.enable`.

## Amendment 4 (keep the last 180 days) - approved and implemented

- [x] `regime.sheet_keep_days` (default 180) with validation, example config, README.
- [x] `stale_row_ranges()` + `RegimeSheetWriter._trim()`; header, today's row, non-date rows and other tabs are never removed; trim failure is a warning.
- [x] Tests: boundary (179 kept / 180 removed), grouping, header safety, non-date rows, today's row with a tiny limit, same-day replace, other tabs untouched, trim failure, config validation, wiring.

## Amendment 5 (tab next to Daily NAV) - approved and implemented

- [x] `RegimeSheetWriter(place_after=...)` inserts a new tab right of the NAV tab; existing tabs are not moved; missing neighbour falls back to the end.
- [x] `main.py` passes the NAV worksheet name it used (including "(Dev)").
- [x] Tests: next-to placement, dev placement, last-position, missing neighbour, no neighbour, existing tab not moved, `main.run` passes the right name.

## Follow-up before enabling regime advice

- [ ] Revisit buy-action wording for BEAR conditions that do not meet the CAPITULATION thresholds. Keep the alert visible, but make its action text consistent with the caution note so the email does not say both “buy aggressively” and “this dip may keep falling.” Consider the same consistency for Tier-1 buys during CORRECTION.
