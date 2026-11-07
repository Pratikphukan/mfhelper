# Design: Market Regime-Aware Signals

**Status: D1-D9 answered by the user (see below). Awaiting explicit sign-off on the points under "Consequences to confirm" before any code is written.**

## Recorded Answers

| # | Decision | Choice |
|---|---|---|
| D1 | Gaps / NEUTRAL | **A.** NEUTRAL leaves today's alerts unchanged. Order: BEAR, CORRECTION (VIX >= 18), UPTREND (VIX < 15 and index > 50D), else NEUTRAL |
| D2 | Flapping | **A.** 5-day average VIX, 3 consecutive days to change regime |
| D3 | Scope | **B.** Every fund that gets technical alerts today (not only equity) |
| D4 | Bear capitulation | **A.** Replace Tier 3 in BEAR with RSI <= 25 AND 200D discount <= -12% (both required), configurable |
| D5 | Suppressed alerts | **A.** Not sent as alerts; listed in a compact "Suppressed by market regime" email section |
| D6 | Buy multipliers | **A.** Text-only suggested multipliers (Tier-1 1.0x, Tier-2 1.5x, Tier-3 2.0x) with regime and valuation modifiers, configurable |
| D7 | Tighten trimming | **A.** At P/E > 24 relax trim thresholds (RSI -5 points, 52W distance +2 points), configurable |
| D8 | Valuation | **A.** P/E thresholds (24 / 18) as trigger; NSE fetch with manual config fallback |
| D9 | Rollout | **A.** `regime.enable` defaults to false; one-line regime banner in the email; no MCP tool yet |

## Consequences to confirm

1. **D3 = all funds.** The regime is computed from NIFTY 500 and India VIX, so it will also gate gold, commodity, and international funds that already receive technical alerts. Example: in a BEAR regime, a gold fund's Tier-1/2/3 dip alerts would be suppressed unless it also meets RSI <= 25 and 200D <= -12%, even if gold is unrelated to the Indian equity downtrend. Debt/liquid/arbitrage/overnight/skip funds are still excluded as today. **[CONFIRM]** or switch to equity-only (or add a per-fund override).
2. **D8 = NSE with manual fallback.** NSE access works from this machine but is unverified from GitHub Actions. If CI is blocked, the daily run uses `valuation.nifty50_pe` from config (stale warning after N days, proposed 7); if neither is available, valuation is "unknown" and neither tightening nor buy expansion is applied. **[CONFIRM]**
3. **D4 in BEAR also covers the trimming side?** Not specified. Proposed: trimming signals are never suppressed by the regime (only buy signals are gated); only valuation (D7) changes trimming. **[CONFIRM]**
4. **Valuation modifiers apply independent of regime.** P/E > 24 halves buy multipliers (0.5x) and tightens trims; P/E < 18 multiplies buy multipliers by 1.25. In BEAR, only capitulation signals exist, so the multiplier applies to those. **[CONFIRM]**

## Amendment 1: the regime advises, it never mutes (APPROVED by the user on 2026-11-07, implemented)

The Recorded Answers table above is the original design. Where it conflicts with this amendment (D2, D4, D5), the amendment wins.

**User principle:** "This is a suggestion. It should not have the power to mute the alerts. The user should read and decide whether to follow it."

This replaces D2, D4 and D5 and changes how D1/D6 are shown. Everything else (D3 scope, D7 trim tightening, D8 valuation source, D9 rollout) is unchanged. Tightening trims only adds alerts, so it does not conflict with the principle.

| Topic | Old (approved) | Proposed |
| --- | --- | --- |
| Which alerts are sent | Regime hides some buy alerts | **Exactly the same alerts as with the feature off.** The regime never removes one. |
| Suppressed list | "Suppressed by market regime" email section | Removed. Nothing is suppressed. |
| Confirmation (D2) | Regime changes after 3 days in a row | Removed. The regime follows each day's market. The `confirm_days` setting and the replay code are deleted. |
| Bear capitulation (D4) | Replaces Tier 3; other buys hidden | Every buy is still sent. A buy that meets RSI <= 25 **and** 200D discount <= -12% is tagged CAPITULATION. In BEAR, other buys get a warning tag. |
| Email "only suppressed" rule | No email if all suppressed | Removed. An email is sent whenever the feature-off run would send one. |

### What the user sees instead (labels on each buy alert)

- UPTREND: "Market is in an uptrend (low VIX). Dips like this have usually been good buys."
- CORRECTION, Tier-1 buy: "Market is volatile (VIX 19.4). Tier-1 dips are weaker in this kind of market. You may want to wait for Tier 2 or 3."
- BEAR, normal buy: "Market is in a downtrend. This dip may keep falling. Only RSI <= 25 with a 200D discount <= -12% counts as capitulation."
- BEAR, capitulation: "CAPITULATION: RSI and 200D discount are both extreme."
- NEUTRAL / data missing: no label.

Suggested size text stays (Tier-1 1.0x, Tier-2 1.5x, Tier-3 2.0x, UPTREND Tier-1 1.5x, P/E 17 modifiers). In CORRECTION and BEAR the normal size is shown next to the warning; no new numbers are invented.

### Safety test
A test runs the same inputs with the feature off and on, in every regime, and asserts the on-run contains every alert the off-run contains.

## Amendment 2: record the market regime in its own Google Sheet tab (APPROVED by the user on 2026-11-07, implemented; see Amendment 3 for two changes)

**User request:** record the regime somewhere, like the Daily NAV. **User choice:** a different sheet is fine; it does not need to go in the Daily NAV sheet. Replace-same-day and keep-all-rows were offered as defaults and not objected to.

### Decisions

| Topic | Proposal |
| --- | --- |
| Where | A new tab **"Market Regime"** in the same spreadsheet (`settings.google_sheet.spreadsheet_id`). The Daily NAV tab and its column layout are never touched. |
| Why not the Daily NAV tab | It is one column group per fund with strict layout guards (`sheet_columns.json`, migrations, 30-row trim). Market data is one set per day, not per fund. Every other feature already uses its own tab (analytics, gold ETF, overlap, historical, portfolio map). |
| Rows | One row per run date. A re-run on the same date **replaces** that date's row (matched on the date part of column A). |
| Retention | Keep all rows. No trimming (about one row a day). |
| When written | Every daily run while `regime.enable` is true, whether or not any alert fires. Nothing is written when the regime is disabled. |
| Dev runs | `--dev` writes to **"Market Regime (Dev)"**, matching the NAV sheet's "(Dev)" tab. |
| Failure | A failed sheet write is logged as a warning and the run continues. It cannot block the NAV row, the alerts, or the email. |
| Missing market data | The row is still written: Regime `NEUTRAL`, number cells blank, reason in Notes. |
| Switch | `regime.record_to_sheet: true` (default true; only takes effect when `regime.enable` is true). |
| Credentials | Reuses the existing Google credentials and `_load_credentials`. No new secrets. |

### Columns

| # | Header | Value |
| --- | --- | --- |
| A | Run Timestamp (IST) | e.g. `2026-11-06 10:30:02` (same format as Daily NAV) |
| B | Regime | BEAR / CORRECTION / UPTREND / NEUTRAL |
| C | NIFTY 500 | latest close, 2 decimals |
| D | 50D SMA | 2 decimals |
| E | 200D SMA | 2 decimals |
| F | VIX (5-day avg) | 2 decimals |
| G | Nifty 50 P/E | 1 decimal |
| H | P/E state | cheap / fair / stretched / unknown |
| I | P/E source | `nse`, `nse_cache (date)`, `manual (date, STALE)`, or blank |
| J | Market data as of | date of the latest NIFTY 500 close |
| K | Notes | e.g. `no ^INDIAVIX data`, `^CRSLDX data is 7 days old` |

### Safety rules

- The writer creates the tab and header if missing. If the tab exists with a **different** header, it refuses to write, logs a warning, and leaves the tab alone (never overwrite someone's data).
- Replace-same-day only edits the matching row. Other rows are never rewritten.
- Header row frozen; number formats applied. Same retry-on-429/5xx helper pattern as the other tab writers.
- Verification uses a fake worksheet. No real sheet is written during development; `--dev` is used for any manual run.

### Not included (can be added later if wanted)

- Backfilling past days from `regime_history`. P/E has no free history, so past rows would have a blank P/E.
- Writing the regime into the alert email on days with no alerts (no email is sent).

## Amendment 3: record first, alerts later (APPROVED by the user on 2026-11-07, implemented)

**User decision:** "Build this now, no alerts for now. We will monitor for a month and then build the alerts."

Changes to Amendment 2 and the earlier design:

| Topic | Change |
| --- | --- |
| Switches | `regime.enable` (advice on alerts) and `regime.record_to_sheet` (daily row) are now **independent**. Both default to false. Recording alone never changes an alert, an email, or adds a banner. The market context is fetched once if either is on. |
| Tab name | Configurable with `regime.sheet_name` (default "Market Regime"); " (Dev)" is appended under `--dev`. |
| Headers | SMA columns are headed "Short SMA" / "Long SMA" and the VIX column "VIX (smoothed)", because the windows (50 / 200 / 5 days) are configurable and the header guard needs fixed text. |
| Rollout | Turn on `record_to_sheet` now. After about a month of rows, review how often each regime fired and decide whether to turn on `enable` (the advice-on-alerts code is already built and tested, and stays off). |

## 1. Where this fits in the current code

- `main.py` computes per-fund `rsi`, `dist_52w_pct`, `dist_200d_sma_pct`, then calls `check_fund_alerts`, `check_confluence_signal` (Tier 1-3 buy, 2-of-3 rules) and `check_trimming_signal` (Trim Tier 1-3). Everything is collected and sent by `dispatch_alerts_email`.
- Funds in categories `debt`, `liquid`, `arbitrage`, `overnight`, `skip` are already excluded from technical alerts. `Fund.category` is optional.
- Benchmark history is fetched via yfinance and cached (`mfhelper/benchmarks.py`, `data/benchmark_history/`). NIFTY 500 is `^CRSLDX`.
- Thresholds live in `AlertRulesConfig` and `config/alerts.yaml`.

Proposed shape: one new pure module `mfhelper/market_regime.py` that takes market data and returns a `MarketContext`; `alerts.py` gains a post-filter that applies it to signals the engine already produces. The existing detection functions stay untouched, so behaviour is identical when the feature is disabled or data is missing.

```text
fetch ^CRSLDX, ^INDIAVIX (+ P/E, + 10Y)  ->  classify_regime()  ->  MarketContext
                                                                        |
per-fund signals (unchanged) --------------> apply_context() --------> surfaced / suppressed / re-sized
                                                                        |
                                                              email: regime banner + suppressed list
```

## 2. Real-data findings that shape the design

Checked against Yahoo Finance data, last 5 years (about 1,230 trading days):

| Fact | Value | Why it matters |
|---|---|---|
| India VIX today | 17.47 (5-day avg 15.89) | Falls in the unassigned 15-18 band |
| NIFTY 500 today | 23,457; +4.3% vs 50D, +3.1% vs 200D; 200D SMA down 0.7% over 20 days | Above both averages |
| VIX < 15 | 59.9% of days | Uptrend rule is common |
| VIX 15-18 | 19.5% of days | **Unassigned in the request** |
| VIX 18-25 | 18.7% of days | Correction rule |
| VIX > 25 | 1.9% of days | **Unassigned in the request** |
| Crossings of VIX 15 / 18 | 75 / 50 | Flapping risk without smoothing |
| Bear rule (index < 200D and 200D falling over 20 days) | 11.0% of days | Reasonably rare |

Data availability (checked from this machine, not from GitHub Actions):

| Series | Source | Result |
|---|---|---|
| NIFTY 500 close | yfinance `^CRSLDX` | Works (already used) |
| India VIX | yfinance `^INDIAVIX` | Works |
| Nifty 50 P/E | NSE `allIndices` JSON API | Works here (Nifty 50 P/E 20.65, Nifty 500 P/E 22.13). Needs a session cookie, and NSE is known to throttle datacenter IPs; `niftyindices.com` already blocked CI once, so **CI access is unverified** |
| Nifty 50 P/E | yfinance | **Not available** |
| 10Y G-Sec yield | yfinance | **Not available** (India tickers return 404) |
| 10Y G-Sec yield | FRED CSV (India long-term rate) | Works, but **monthly** with about 1-2 month lag (latest value Sep 2026: 7.06%) |

Yield-gap caveat: earnings yield = 1 / P/E. At P/E 20.65 it is 4.84%, below the 7.06% 10Y yield, so the gap is **negative (-2.2 points)**. With the 10Y near 7%, the gap is negative for any P/E above about 14, so a yield-gap rule would call the market expensive at P/E 18 and 24 alike. P/E thresholds (18 and 24) and the yield gap are therefore **different tests that give different answers today**, and one must be chosen as the primary rule.

## 3. Open decisions

### D1. Regime definitions, gaps, and precedence

Proposed rule set, evaluated top to bottom, first match wins:

| Order | Regime | Condition |
|---|---|---|
| 1 | BEAR | Index close < 200D SMA **and** 200D SMA lower than 20 trading days ago |
| 2 | CORRECTION | VIX >= 18 (no upper cap, so the >25 gap becomes correction) |
| 3 | UPTREND | VIX < 15 **and** index close > 50D SMA |
| 4 | NEUTRAL | Everything else (VIX 15-18, or VIX < 15 with index below its 50D SMA) |

- A. **Proposed:** NEUTRAL leaves today's behaviour completely unchanged (current thresholds, no suppression, no re-sizing).
- B. Map each gap to its nearest regime instead of having a NEUTRAL state (always acting on a regime, but bands are then invented).
- C. Add a fifth PANIC regime for VIX > 25 that is allowed to surface Tier-3 buys (explicitly treats extreme fear as opportunity).

With the proposal, today (VIX 17.47, index above both SMAs) is **NEUTRAL**.

### D2. Smoothing to avoid flapping

- A. **Proposed:** classify on the **5-day average VIX** with a confirmation rule: a regime change takes effect only after 3 consecutive days in the new regime.
- B. Hysteresis bands (for example enter UPTREND below 15, leave above 16.5; enter CORRECTION above 18, leave below 16.5).
- C. Raw daily values, no smoothing (simplest; will flip often).

### D3. Which funds the regime applies to

The regime describes the Indian equity market only.

- A. **Proposed:** apply to funds whose `category` is unset or `equity`; gold, commodity, international, and debt-like categories keep today's behaviour. (Needs a category audit of `config/*.yaml`; `international.yaml` and `gold_etfs.yaml` exist.)
- B. Apply to every fund that already receives technical alerts.
- C. Add a per-fund `regime: on|off` override in the YAML on top of A.

### D4. How bear-regime "capitulation" is detected

Existing Tier 3 is any 2 of: RSI <= 35, 200D discount <= -10%, 52W drop <= -20%.

- A. **Proposed:** in BEAR, replace Tier 3 with a stricter "Capitulation" rule: **RSI <= 25 AND 200D SMA discount <= -12%** (both required), configurable. Tiers 1 and 2 are suppressed.
- B. Keep 2-of-3 but with stricter thresholds (RSI <= 25, 200D <= -12%, 52W <= -25%).
- C. Add a separate Tier 4 label on top of the existing Tier 3 so both can appear.

### D5. What "suppress" and "conservative" mean

- A. **Proposed:** suppressed signals are **not** sent as alerts, but the email lists them in a compact "Suppressed by market regime" section (fund, tier, reason) so nothing disappears silently.
- B. Suppress completely; log only.
- C. Downgrade instead of suppress (for example Tier-1 shown as "watch only").

CORRECTION: suppress Tier-1, surface Tier-2 and Tier-3. BEAR: surface only capitulation. UPTREND: surface all tiers, and mark Tier-1 as "high-conviction" with a stronger suggestion. NEUTRAL: unchanged.

### D6. "Buy multipliers" (new concept)

No numeric multiplier exists today. Proposed: add a configurable **suggested multiplier** per tier (Tier-1 1.0x, Tier-2 1.5x, Tier-3 2.0x of the user's normal SIP/top-up) that is **text only** in the email, plus regime and valuation modifiers:

| Condition | Modifier (Proposed defaults, all configurable) |
|---|---|
| UPTREND | Tier-1 uses 1.5x instead of 1.0x |
| Cheap valuation (P/E < 18) | multiply by 1.25 |
| Stretched valuation (P/E > 24) | multiply by 0.5 for any buy |

- A. **Proposed:** text-only multipliers as above.
- B. Do not introduce numbers; only reword suggestions ("increase top-up").
- C. Numbers tied to an explicit monthly budget in config (needs a budget amount; adds a new concept).

### D7. How trimming "tightens" at stretched valuation

Existing Trim Tiers: T1 RSI >= 65 and 52W >= -5%; T2 RSI >= 70 and >= -3%; T3 RSI >= 75 and >= -1% (2 of 2).

- A. **Proposed:** when P/E > 24, relax each trim threshold toward the current price by configurable offsets (RSI -5 points, 52W distance +2 points), so trims fire earlier. The inverse is **not** applied when valuations are cheap.
- B. Promote one tier (a T1 signal is displayed as T2, T2 as T3) at stretched valuation.
- C. Only add a warning banner; thresholds unchanged.

### D8. Valuation metric and data source

Pick the primary rule:

- A. **Nifty 50 P/E only** (24 / 18 as requested). Yield gap shown for information only if a yield is available.
- B. Equity yield gap only (needs a 10Y source). Given the 7% yield, thresholds would have to be redefined, since the gap is negative across the normal P/E range.
- C. Both, with P/E as the trigger and yield gap as a confirming note.

Source for P/E:

- S1. **NSE `allIndices` API**, fetched daily and cached (works here; may be blocked from GitHub Actions, in which case it falls back below).
- S2. **Manual value in config** (`valuation.nifty50_pe`) that you update yourself, with a "stale after N days" warning. Always works, never automatic.
- S3. S1 with automatic fallback to S2. **Proposed.**
- S4. Skip valuation in the first release and ship the regime filter only.

Source for the 10Y yield, if used: FRED monthly (lagging, free), or the manual config value. Intraday precision is not needed for a context note.

### D9. Failure handling, rollout, and display

- Proposed: if market data is missing or stale (more than 5 days old), regime = NEUTRAL, valuation = unknown, and the email says "market context unavailable". Alerts are never dropped because a data fetch failed.
- Proposed: config section `regime:` in `alerts.yaml` with `enable: false` by default so existing users see no change until they opt in. All thresholds above are configurable with the proposed defaults.
- Proposed: email gets a one-line regime banner (regime, VIX, index vs 50D/200D, P/E) at the top. No Google Sheet layout changes in this change.
- MCP tools (`agent_tools.py`) get a read-only `get_market_regime()` tool; the existing screening tool reports the regime. (Confirm whether this is wanted in the first release.)

## 4. Proposed data model

```python
class Regime(str, Enum):
    UPTREND = "uptrend"; CORRECTION = "correction"; BEAR = "bear"; NEUTRAL = "neutral"

@dataclass(frozen=True)
class MarketContext:
    as_of: date
    regime: Regime
    vix: float | None; vix_avg_5d: float | None
    index_close: float | None; dist_50d_pct: float | None; dist_200d_pct: float | None
    sma200_slope_pct: float | None          # change over 20 trading days
    pe: float | None; pe_source: str | None  # "nse" | "manual" | None
    valuation: Literal["cheap", "neutral", "stretched", "unknown"]
    notes: list[str]                         # e.g. "VIX data stale", "regime held by 3-day confirmation"
```

`apply_context(signals, context, rules) -> ContextResult(surfaced, suppressed, notes)` is pure and unit-testable with no network.

## 5. Safety and testing

- All market fetches reuse the existing yfinance cache pattern; new cache files go under `data/` and are git-ignored.
- Pure functions get table-driven unit tests for every regime boundary (14.99/15/17.99/18/25/25.01), precedence overlaps, smoothing and confirmation, gap handling, missing-data fallbacks, and each suppression rule. Fetchers are tested with fakes; no network in tests.
- Development runs use `--dev` and sandbox sheets only. No live emails or production sheets.
- Verify that with `regime.enable: false` the alert output is byte-for-byte the same as today.
- Compare the regime history against real data (VIX and NIFTY 500 are free for 15+ years) to report how many days each regime would have been active and how many alerts it would have suppressed. P/E has no free history, so valuation cannot be back-tested.
