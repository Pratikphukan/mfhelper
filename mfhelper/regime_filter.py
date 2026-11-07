"""Apply a ``MarketContext`` to the per-fund alert results.

Only BUY-side signals are gated by the regime. SELL / TRIM / CROSS-BELOW alerts are
never suppressed; the only thing that changes them is a stretched Nifty 50 P/E, which
makes the trim thresholds fire earlier. Valuation modifies suggested buy size
regardless of regime. Sizes are text in the email, never an order.

Per regime, for a fund that already gets technical alerts:

* NEUTRAL     unchanged
* UPTREND     unchanged; a Tier-1 confluence is sized at ``multiplier_uptrend_tier1``
* CORRECTION  BUY TIER 1 single-indicator alerts and a Tier-1 confluence are suppressed
* BEAR        all BUY alerts and the BULLISH CROSS-ABOVE alert are suppressed unless the
              fund hits capitulation (RSI and 200D SMA discount both extreme). Then only
              its BUY TIER 3 alerts survive and a Tier-3 capitulation signal replaces the
              normal confluence signal.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
import urllib.parse

from mfhelper.alerts import (
    DipBuyingSignal,
    TriggeredAlert,
    TrimmingSignal,
    check_trimming_signal,
    format_multiplier,
)
from mfhelper.config import AlertRulesConfig, RegimeSettings
from mfhelper.market_regime import MarketContext, Regime, SuppressedSignal

_BUY_TIER = re.compile(r"^BUY TIER (\d)")


@dataclass(frozen=True)
class BuyDecision:
    alerts: list[TriggeredAlert]
    confluence: DipBuyingSignal | None
    suppressed: SuppressedSignal | None


def buy_tier(alert: TriggeredAlert) -> int | None:
    match = _BUY_TIER.match(alert.alert_type)
    return int(match.group(1)) if match else None


def is_bullish_cross(alert: TriggeredAlert) -> bool:
    return "CROSS-ABOVE" in alert.alert_type


def meets_capitulation(rsi: float | None, dist_200d_sma: float | None, cfg: RegimeSettings) -> bool:
    """Both conditions are required, and a missing indicator never qualifies."""
    return (
        rsi is not None
        and dist_200d_sma is not None
        and rsi <= cfg.capitulation_rsi
        and dist_200d_sma <= cfg.capitulation_sma_discount_pct
    )


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


def with_size(signal: DipBuyingSignal, context: MarketContext, cfg: RegimeSettings) -> DipBuyingSignal:
    multiplier, note = size_multiplier(signal.tier, context, cfg)
    return replace(signal, multiplier=multiplier, context_note=note)


def _capitulation_signal(
    scheme_code: str, fund_name: str, rsi: float, dist_200d: float, cfg: RegimeSettings
) -> DipBuyingSignal:
    return DipBuyingSignal(
        scheme_code=scheme_code,
        fund_name=fund_name,
        tier=3,
        reasons=[
            f"RSI is {rsi:.2f} (Capitulation, <= {cfg.capitulation_rsi:g})",
            f"200D SMA is {dist_200d:.2f}% (Capitulation, <= {cfg.capitulation_sma_discount_pct:g}%)",
        ],
        suggestion=(
            "Capitulation Buy (bear market). RSI and the 200D SMA discount are both at extreme "
            "levels while the broad market is in a confirmed downtrend."
        ),
        groww_link=f"https://groww.in/mutual-funds/search?q={urllib.parse.quote_plus(fund_name)}",
    )


def _suppressed(
    scheme_code: str, fund_name: str, dropped_alerts: int, dropped_confluence: DipBuyingSignal | None, reason: str
) -> SuppressedSignal | None:
    parts = []
    if dropped_confluence is not None:
        parts.append(f"Tier-{dropped_confluence.tier} confluence buy")
    if dropped_alerts:
        parts.append(f"{dropped_alerts} single-indicator buy alert{'s' if dropped_alerts != 1 else ''}")
    if not parts:
        return None
    return SuppressedSignal(scheme_code, fund_name, " + ".join(parts), reason)


def apply_regime_to_buys(
    context: MarketContext,
    cfg: RegimeSettings,
    *,
    scheme_code: str,
    fund_name: str,
    rsi: float | None,
    dist_200d_sma: float | None,
    alerts: list[TriggeredAlert],
    confluence: DipBuyingSignal | None,
) -> BuyDecision:
    """Gate and size one fund's buy-side output. Non-buy alerts always pass through."""
    regime = context.regime

    if regime is Regime.BEAR:
        if meets_capitulation(rsi, dist_200d_sma, cfg):
            kept = [a for a in alerts if (buy_tier(a) is None and not is_bullish_cross(a)) or buy_tier(a) == 3]
            signal = _capitulation_signal(scheme_code, fund_name, rsi, dist_200d_sma, cfg)  # type: ignore[arg-type]
            return BuyDecision(kept, with_size(signal, context, cfg), None)
        kept = [a for a in alerts if buy_tier(a) is None and not is_bullish_cross(a)]
        rsi_text = f"{rsi:.1f}" if rsi is not None else "n/a"
        dist_text = f"{dist_200d_sma:.1f}%" if dist_200d_sma is not None else "n/a"
        reason = (
            f"BEAR: needs RSI <= {cfg.capitulation_rsi:g} and 200D SMA discount <= "
            f"{cfg.capitulation_sma_discount_pct:g}% (now RSI {rsi_text}, {dist_text})"
        )
        return BuyDecision(
            kept, None, _suppressed(scheme_code, fund_name, len(alerts) - len(kept), confluence, reason)
        )

    if regime is Regime.CORRECTION:
        kept = [a for a in alerts if buy_tier(a) != 1]
        dropped_confluence = confluence if confluence is not None and confluence.tier == 1 else None
        survivor = None if dropped_confluence else confluence
        return BuyDecision(
            kept,
            with_size(survivor, context, cfg) if survivor else None,
            _suppressed(
                scheme_code, fund_name, len(alerts) - len(kept), dropped_confluence,
                "CORRECTION: Tier-1 buys are suppressed",
            ),
        )

    # NEUTRAL (including "market context unavailable") and UPTREND: nothing is suppressed.
    return BuyDecision(alerts, with_size(confluence, context, cfg) if confluence else None, None)


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
