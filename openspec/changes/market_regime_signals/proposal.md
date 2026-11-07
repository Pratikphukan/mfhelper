# Proposal: Market Regime-Aware Dip-Buying (Contextual Signal Engine)

## Status

**Decisions D1-D9 answered (see `design.md`). Awaiting sign-off on four consequences. No code or tests yet.**

## Problem

Dip-buying and trimming alerts use fixed thresholds (`config/alerts.yaml`: RSI, 200D SMA distance, 52W high distance, 2-of-3 confluence per tier). The same -5% dip triggers the same alert in a raging bull market, where it is an aggressive buy, and in a macro downtrend, where it may be a falling knife. Valuation is also ignored: the same buy or trim alert fires whether the market is cheap or stretched.

## Objective

Add a market-wide context layer that adjusts *how existing signals are treated*, without replacing them:

1. **Regime filter** from NIFTY 500 and India VIX decides which dip-buy tiers are surfaced, suppressed, or tightened.
2. **Valuation context** (Nifty 50 P/E, optionally the equity yield gap versus the 10-year G-Sec) tightens trim alerts when the market is expensive and expands buy sizing when it is cheap.

## Requested behaviour (from the requester)

| Regime | Trigger | Dip-buy treatment |
|---|---|---|
| Uptrend / low volatility | VIX < 15 and index > 50D SMA | Aggressive: Tier-1 mild pullbacks are high-conviction buys |
| Correction / high volatility | VIX 18-25 | Conservative: suppress Tier-1; notify only Tier-2/3 |
| Bear / capitulation | Index < 200D SMA with downward slope | Capital preservation: notify only generational capitulation (e.g. RSI < 25 and 200D SMA discount > 12%) |

| Valuation | Trigger | Treatment |
|---|---|---|
| Stretched | Nifty 50 P/E > 24 | Tighten trimming alerts |
| Cheap | Nifty 50 P/E < 18 | Expand buy multipliers |

## Gaps in the request that need a decision

These were found by checking the request against the current code and 5 years of real data (details in `design.md`):

1. **Uncovered VIX ranges.** VIX 15-18 and VIX > 25 are not assigned to any regime. Over the last 5 years about **21% of days** fell in those gaps (19.5% in 15-18, 1.9% above 25). Today's VIX is 17.47.
2. **Overlap and precedence.** The bear rule (index-based) can hold at the same time as a low VIX or a high VIX.
3. **Flapping.** VIX crossed 15 about 75 times and 18 about 50 times in 5 years, so a raw daily threshold would flip regimes often.
4. **"Buy multipliers" do not exist yet.** Alerts only carry text such as "increased SIP multiplier". There is no numeric multiplier to expand.
5. **"Tighten trimming" is undefined.** Which thresholds change, and by how much?
6. **P/E and G-Sec yield have no yfinance ticker.** They need a different source, and P/E and yield gap disagree at today's yields (see `design.md`).
7. **Scope.** The index regime says nothing about gold, international, or debt funds.

## Out of scope

Automatic order placement, backtesting P&L, intraday data, per-fund (non-index) regimes, changing the existing threshold values in `alerts.yaml`, and replacing the current alert email layout beyond adding regime context.
