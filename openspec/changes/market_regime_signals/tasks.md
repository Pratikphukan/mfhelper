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
- [ ] Open question for the user: a daily regime line on days with no alerts (would mean an email every day). Not implemented.
