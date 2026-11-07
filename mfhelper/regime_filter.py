"""Add market-regime advice to the per-fund alert results.

The regime is advice only. Nothing here removes, hides, or reorders an alert: the
alerts and signals that go in are the ones that come out, with an optional note and
a suggested size attached. The only thing that can change *which* alerts exist is a
stretched Nifty 50 P/E, which makes trim thresholds fire earlier (more alerts).

Notes on BUY alerts, by regime:

* UPTREND     "dips like this have usually been good buys"
* CORRECTION  a Tier-1 buy is flagged as weaker; Tier 2 and 3 get no regime note
* BEAR        a buy with RSI and 200D SMA discount both extreme is tagged CAPITULATION;
              every other buy carries a falling-knife warning
* NEUTRAL     no note (also used when market data is unavailable)

Sizes are text in the email (a multiple of the user's normal top-up), never an order.
"""

from __future__ import annotations

from dataclasses import replace
import re

from mfhelper.alerts import (
    DipBuyingSignal,
    TriggeredAlert,
    TrimmingSignal,
    check_trimming_signal,
    format_multiplier,
)
from mfhelper.config import AlertRulesConfig, RegimeSettings
from mfhelper.market_regime import MarketContext, Regime

_BUY_TIER = re.compile(r"^BUY TIER (\d)")


def buy_tier(alert: TriggeredAlert) -> int | None:
    match = _BUY_TIER.match(alert.alert_type)
    return int(match.group(1)) if match else None


def meets_capitulation(rsi: float | None, dist_200d_sma: float | None, cfg: RegimeSettings) -> bool:
    """Both conditions are required, and a missing indicator never qualifies."""
    return (
        rsi is not None
        and dist_200d_sma is not None
        and rsi <= cfg.capitulation_rsi
        and dist_200d_sma <= cfg.capitulation_sma_discount_pct
    )


def regime_note(
    tier: int,
    context: MarketContext,
    cfg: RegimeSettings,
    rsi: float | None,
    dist_200d_sma: float | None,
) -> str:
    """The advice sentence for a buy of ``tier``; empty when the regime has no view."""
    regime = context.regime
    if regime is Regime.UPTREND:
        return "Market is in an uptrend (low VIX). Dips like this have usually been good buys."
    if regime is Regime.CORRECTION and tier == 1:
        vix = f" (VIX avg {context.vix_avg:.1f})" if context.vix_avg is not None else ""
        return (
            f"Market is volatile{vix}. Tier-1 dips are weaker in this kind of market. "
            "You may want to wait for Tier 2 or 3."
        )
    if regime is Regime.BEAR:
        if meets_capitulation(rsi, dist_200d_sma, cfg):
            return (
                f"CAPITULATION: RSI {rsi:.1f} and 200D SMA discount {dist_200d_sma:.1f}% are both extreme."
            )
        return (
            "Market is in a downtrend. This dip may keep falling. Only RSI <= "
            f"{cfg.capitulation_rsi:g} with a 200D SMA discount <= {cfg.capitulation_sma_discount_pct:g}% "
            "counts as capitulation."
        )
    return ""


def size_multiplier(tier: int, context: MarketContext, cfg: RegimeSettings) -> tuple[float, str]:
    """Suggested buy size (times the user's normal top-up) and the reasons behind it."""
    base = {1: cfg.multiplier_tier1, 2: cfg.multiplier_tier2, 3: cfg.multiplier_tier3}[tier]
    notes: list[str] = []
    if tier == 1 and context.regime is Regime.UPTREND:
        base = cfg.multiplier_uptrend_tier1
        notes.append(f"UPTREND sizing for Tier-1 ({format_multiplier(base)})")

    valuation = context.valuation
    factor = 1.0
    if valuation.pe is not None and valuation.state == "cheap":
        factor = cfg.multiplier_cheap_factor
        notes.append(f"Nifty 50 P/E {valuation.pe:.1f} < {cfg.pe_cheap:g}: x{factor:g}")
    elif valuation.pe is not None and valuation.state == "stretched":
        factor = cfg.multiplier_stretched_factor
        notes.append(f"Nifty 50 P/E {valuation.pe:.1f} > {cfg.pe_stretched:g}: x{factor:g}")
    return base * factor, "; ".join(notes)


def annotate_buys(
    context: MarketContext,
    cfg: RegimeSettings,
    *,
    rsi: float | None,
    dist_200d_sma: float | None,
    alerts: list[TriggeredAlert],
    confluence: DipBuyingSignal | None,
) -> tuple[list[TriggeredAlert], DipBuyingSignal | None]:
    """Attach advice to one fund's buy alerts and confluence signal.

    Returns the same alerts and signal, in the same order, with notes (and a size on the
    confluence signal) added. Alerts that are not BUY TIER alerts are returned untouched.
    """
    annotated: list[TriggeredAlert] = []
    for alert in alerts:
        tier = buy_tier(alert)
        note = regime_note(tier, context, cfg, rsi, dist_200d_sma) if tier is not None else ""
        annotated.append(replace(alert, context_note=note) if note else alert)

    if confluence is None:
        return annotated, None

    multiplier, size_notes = size_multiplier(confluence.tier, context, cfg)
    parts = [regime_note(confluence.tier, context, cfg, rsi, dist_200d_sma)]
    if size_notes:
        parts.append(f"Sizing: {size_notes}.")
    return annotated, replace(confluence, multiplier=multiplier, context_note=" ".join(p for p in parts if p))


def check_trimming_for_context(
    context: MarketContext,
    cfg: RegimeSettings,
    *,
    scheme_code: str,
    fund_name: str,
    rsi: float | None,
    dist_52w: float | None,
    rules: AlertRulesConfig,
) -> TrimmingSignal | None:
    """Trim check that fires earlier while the Nifty 50 P/E is above ``pe_stretched``."""
    valuation = context.valuation
    if valuation.pe is None or valuation.state != "stretched":
        return check_trimming_signal(scheme_code, fund_name, rsi, dist_52w, rules)

    tightened = check_trimming_signal(
        scheme_code, fund_name, rsi, dist_52w, rules,
        rsi_offset=cfg.trim_rsi_offset, dist_52w_offset=cfg.trim_52w_offset_pts,
    )
    if tightened is None:
        return None
    standard = check_trimming_signal(scheme_code, fund_name, rsi, dist_52w, rules)
    if standard is not None and standard.tier == tightened.tier:
        return tightened  # would have fired anyway, nothing to explain
    note = (
        f"Fired earlier than usual: Nifty 50 P/E {valuation.pe:.1f} > {cfg.pe_stretched:g} "
        f"(RSI thresholds -{cfg.trim_rsi_offset:g}, 52W window +{cfg.trim_52w_offset_pts:g} pts)"
    )
    return replace(tightened, context_note=note)
