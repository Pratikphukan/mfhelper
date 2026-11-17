"""Present technical dip signals with market-regime context, without sizing advice."""

from __future__ import annotations

from dataclasses import replace
import re

from mfhelper.alerts import (
    DipBuyingSignal,
    TriggeredAlert,
    TrimmingSignal,
    check_trimming_signal,
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


def regime_advice(
    tier: int,
    context: MarketContext,
    cfg: RegimeSettings,
    rsi: float | None,
    dist_200d_sma: float | None,
) -> tuple[str, str, str]:
    """Return display label, cautious action text, and factual context for a dip signal."""
    regime = context.regime
    if regime is Regime.BEAR:
        if meets_capitulation(rsi, dist_200d_sma, cfg):
            label = f"CAPITULATION DETECTED — REVIEW BEFORE DECIDING · TECHNICAL DIP TIER {tier}"
            suggestion = (
                "Both configured capitulation thresholds are met. This is an extreme-dip signal, "
                "not proof the fund has bottomed. Review before deciding."
            )
            context_note = (
                f"RSI {rsi:.1f} <= {cfg.capitulation_rsi:g} and 200D SMA distance "
                f"{dist_200d_sma:.1f}% <= {cfg.capitulation_sma_discount_pct:g}%.")
            return label, suggestion, context_note
        label = f"DIP DETECTED — WATCH · TECHNICAL DIP TIER {tier}"
        suggestion = (
            "A technical dip signal appeared while the broad market meets MFHelper's BEAR rule. "
            "This does not predict the fund's next move. Watch and review before deciding."
        )
        missing = []
        if rsi is None:
            missing.append("RSI is unavailable")
        elif rsi > cfg.capitulation_rsi:
            missing.append(f"RSI {rsi:.1f} is above {cfg.capitulation_rsi:g}")
        if dist_200d_sma is None:
            missing.append("200D SMA distance is unavailable")
        elif dist_200d_sma > cfg.capitulation_sma_discount_pct:
            missing.append(f"200D SMA distance {dist_200d_sma:.1f}% is above {cfg.capitulation_sma_discount_pct:g}%")
        context_note = "Capitulation thresholds not met: " + "; ".join(missing) + "."
        return label, suggestion, context_note

    if regime is Regime.CORRECTION:
        vix_detail = (
            f"Five-session average VIX is {context.vix_avg:.1f}."
            if context.vix_avg is not None
            else "The market is classified as CORRECTION because volatility is elevated."
        )
        if tier == 1:
            return (
                "WATCH · TECHNICAL DIP TIER 1",
                "Tier 1 is a weaker signal during elevated volatility. Watch; review again if Tier 2 or 3 appears.",
                vix_detail,
            )
        return (
            f"REVIEW SIGNAL · TECHNICAL DIP TIER {tier}",
            "A stronger technical dip signal appeared during elevated volatility. Review before deciding.",
            vix_detail,
        )

    if regime is Regime.UPTREND:
        return (
            f"TECHNICAL DIP TIER {tier}",
            "Technical dip conditions are present. Review the indicators; no amount is suggested.",
            "The broad-market regime is UPTREND; this is not a prediction for the individual fund.",
        )
    if not context.available:
        return (
            f"TECHNICAL DIP TIER {tier}",
            "Technical dip conditions are present. Review the indicators; no amount is suggested.",
            "Market-regime data is unavailable, so this signal has no broad-market context.",
        )
    return (
        f"TECHNICAL DIP TIER {tier}",
        "Technical dip conditions are present. Review the indicators; no amount is suggested.",
        "MFHelper has no UPTREND, CORRECTION, or BEAR view for the broad market today.",
    )


def annotate_buys(
    context: MarketContext,
    cfg: RegimeSettings,
    *,
    rsi: float | None,
    dist_200d_sma: float | None,
    alerts: list[TriggeredAlert],
    confluence: DipBuyingSignal | None,
) -> tuple[list[TriggeredAlert], DipBuyingSignal | None]:
    """Attach non-directive regime wording to one fund's buy alerts and confluence signal."""
    annotated: list[TriggeredAlert] = []
    for alert in alerts:
        tier = buy_tier(alert)
        if tier is None:
            annotated.append(alert)
            continue
        label, suggestion, note = regime_advice(tier, context, cfg, rsi, dist_200d_sma)
        annotated.append(replace(
            alert,
            action_suggestion=suggestion,
            context_note=note,
            display_label=label,
        ))

    if confluence is None:
        return annotated, None

    label, suggestion, note = regime_advice(confluence.tier, context, cfg, rsi, dist_200d_sma)
    return annotated, replace(
        confluence,
        multiplier=None,
        suggestion=suggestion,
        context_note=note,
        display_label=label,
    )


def check_trimming_for_context(
    context: MarketContext,
    cfg: RegimeSettings,
    *,
    scheme_code: str,
    fund_name: str,
    rsi: float | None,
    dist_52w: float | None,
    rules: AlertRulesConfig,
    groww_link: str | None = None,
) -> TrimmingSignal | None:
    """Trim check that fires earlier while the Nifty 50 P/E is above ``pe_stretched``."""
    valuation = context.valuation
    if valuation.source != "nse" or valuation.pe is None or valuation.state != "stretched":
        return check_trimming_signal(scheme_code, fund_name, rsi, dist_52w, rules, groww_link=groww_link)

    tightened = check_trimming_signal(
        scheme_code, fund_name, rsi, dist_52w, rules,
        groww_link=groww_link,
        rsi_offset=cfg.trim_rsi_offset, dist_52w_offset=cfg.trim_52w_offset_pts,
    )
    if tightened is None:
        return None
    standard = check_trimming_signal(scheme_code, fund_name, rsi, dist_52w, rules, groww_link=groww_link)
    if standard is not None and standard.tier == tightened.tier:
        return tightened  # would have fired anyway, nothing to explain
    note = (
        f"Fired earlier than usual: Nifty 50 P/E {valuation.pe:.1f} > {cfg.pe_stretched:g} "
        f"(RSI thresholds -{cfg.trim_rsi_offset:g}, 52W window +{cfg.trim_52w_offset_pts:g} pts)"
    )
    return replace(tightened, context_note=note)
