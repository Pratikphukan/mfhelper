"""Technical indicators alert rules checker and email dispatcher."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from mfhelper.config import AlertEmailConfig, AlertRulesConfig
from mfhelper.metrics import distance_from_200d_sma

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TriggeredAlert:
    scheme_code: str
    fund_name: str
    indicator_name: str      # e.g., "RSI (14)", "52W High Distance", "200D SMA Distance"
    current_value: float
    trigger_level: float
    alert_type: str          # e.g., "BUY TIER 1", "BUY TIER 3", "MOMENTUM WARNING", etc.
    action_suggestion: str


@dataclass(frozen=True)
class DipBuyingSignal:
    scheme_code: str
    fund_name: str
    tier: int               # 1, 2, or 3
    reasons: list[str]      # e.g., ["RSI is 32.5 (Oversold)", "52W Drop is -22.4% (Deep)"]
    suggestion: str
    groww_link: str         # Direct buy button link


def check_confluence_signal(
    scheme_code: str,
    fund_name: str,
    current_rsi: float | None,
    current_dist_52w: float | None,
    current_dist_200d_sma: float | None,
    rules: AlertRulesConfig,
) -> DipBuyingSignal | None:
    """Check today's indicators for a single fund to see if they form a confluent buying signal."""
    import urllib.parse
    groww_query = urllib.parse.quote_plus(fund_name)
    groww_link = f"https://groww.in/mutual-funds/search?q={groww_query}"

    # Tier 3 (Deep/Strong Buy)
    t3_reasons = []
    if current_rsi is not None and current_rsi <= rules.rsi_deep_oversold:
        t3_reasons.append(f"RSI is {current_rsi:.2f} (Deeply Oversold)")
    if current_dist_200d_sma is not None and current_dist_200d_sma <= rules.sma_deep_capitulation_pct:
        t3_reasons.append(f"200D SMA is {current_dist_200d_sma:.2f}% (Capitulation)")
    if current_dist_52w is not None and current_dist_52w <= rules.discount_deep_pct:
        t3_reasons.append(f"52W Drop is {current_dist_52w:.2f}% (Deep Discount)")

    if len(t3_reasons) >= 2:
        return DipBuyingSignal(
            scheme_code=scheme_code,
            fund_name=fund_name,
            tier=3,
            reasons=t3_reasons,
            suggestion="Strong Confluence Buy. Fund is highly oversold and deeply discounted from peak. Suggesting aggressive lumpsum top-up.",
            groww_link=groww_link,
        )

    # Tier 2 (Moderate Buy)
    t2_reasons = []
    if current_rsi is not None and current_rsi <= rules.rsi_moderate_dip:
        t2_reasons.append(f"RSI is {current_rsi:.2f} (Moderate Dip)")
    if current_dist_200d_sma is not None and current_dist_200d_sma <= rules.sma_moderate_discount_pct:
        t2_reasons.append(f"200D SMA is {current_dist_200d_sma:.2f}% (Support Discount)")
    if current_dist_52w is not None and current_dist_52w <= rules.discount_moderate_pct:
        t2_reasons.append(f"52W Drop is {current_dist_52w:.2f}% (Moderate Discount)")

    if len(t2_reasons) >= 2:
        return DipBuyingSignal(
            scheme_code=scheme_code,
            fund_name=fund_name,
            tier=2,
            reasons=t2_reasons,
            suggestion="Moderate Confluence Buy. Solid support dip. Suggesting moderate lumpsum or increased SIP multiplier.",
            groww_link=groww_link,
        )

    # Tier 1 (Mild Pullback Buy)
    t1_reasons = []
    if current_rsi is not None and current_rsi <= rules.rsi_mild_pullback:
        t1_reasons.append(f"RSI is {current_rsi:.2f} (Mild Pullback)")
    if current_dist_200d_sma is not None and (current_dist_200d_sma <= rules.sma_trend_support_pct or abs(current_dist_200d_sma) <= rules.sma_trend_support_pct):
        t1_reasons.append(f"200D SMA is {current_dist_200d_sma:.2f}% (Trend Support)")
    if current_dist_52w is not None and current_dist_52w <= rules.discount_mild_pct:
        t1_reasons.append(f"52W Drop is {current_dist_52w:.2f}% (Mild Discount)")

    if len(t1_reasons) >= 2:
        return DipBuyingSignal(
            scheme_code=scheme_code,
            fund_name=fund_name,
            tier=1,
            reasons=t1_reasons,
            suggestion="Mild Confluence Pullback. Healthy consolidation. Suggesting standard top-up.",
            groww_link=groww_link,
        )

    return None


@dataclass(frozen=True)
class TrimmingSignal:
    scheme_code: str
    fund_name: str
    tier: int               # 1, 2, or 3
    reasons: list[str]      # e.g., ["RSI is 76.5 (Overbought)", "52W Drop is -0.5% (Peak)"]
    suggestion: str
    groww_link: str         # Direct search page link


def check_trimming_signal(
    scheme_code: str,
    fund_name: str,
    current_rsi: float | None,
    current_dist_52w: float | None,
    rules: AlertRulesConfig,
) -> TrimmingSignal | None:
    """Check today's indicators for a single fund to see if they form an overbought trimming signal."""
    import urllib.parse
    groww_query = urllib.parse.quote_plus(fund_name)
    groww_link = f"https://groww.in/mutual-funds/search?q={groww_query}"

    # Trim Tier 3 (Extreme Climax Peak - Urgent Action)
    t3_reasons = []
    if current_rsi is not None and current_rsi >= 75.0:
        t3_reasons.append(f"RSI is {current_rsi:.2f} (Extreme Overbought)")
    if current_dist_52w is not None and current_dist_52w >= -1.0:
        t3_reasons.append(f"52W Drop is {current_dist_52w:.2f}% (Urgent Peak)")

    if len(t3_reasons) >= 2:
        return TrimmingSignal(
            scheme_code=scheme_code,
            fund_name=fund_name,
            tier=3,
            reasons=t3_reasons,
            suggestion="Urgent Climax Warning. Fund is trading at extreme peak overbought conditions. Strongly suggesting trimming 5% to 10% of total profits to cash and pausing all SIPs immediately.",
            groww_link=groww_link,
        )

    # Trim Tier 2 (Moderate Overstretch - Trim Zone)
    t2_reasons = []
    if current_rsi is not None and current_rsi >= 70.0:
        t2_reasons.append(f"RSI is {current_rsi:.2f} (Standard Overbought)")
    if current_dist_52w is not None and current_dist_52w >= -3.0:
        t2_reasons.append(f"52W Drop is {current_dist_52w:.2f}% (Near Peak)")

    if len(t2_reasons) >= 2:
        return TrimmingSignal(
            scheme_code=scheme_code,
            fund_name=fund_name,
            tier=2,
            reasons=t2_reasons,
            suggestion="Moderate Overstretch. Strong uptrend momentum, but entering the trim zone. Suggesting pausing manual top-ups and considering locking in partial profits.",
            groww_link=groww_link,
        )

    # Trim Tier 1 (Mild Momentum Run)
    t1_reasons = []
    if current_rsi is not None and current_rsi >= 65.0:
        t1_reasons.append(f"RSI is {current_rsi:.2f} (Mild Momentum)")
    if current_dist_52w is not None and current_dist_52w >= -5.0:
        t1_reasons.append(f"52W Drop is {current_dist_52w:.2f}% (Close to Peak)")

    if len(t1_reasons) >= 2:
        return TrimmingSignal(
            scheme_code=scheme_code,
            fund_name=fund_name,
            tier=1,
            reasons=t1_reasons,
            suggestion="Mild Momentum Run. Strong trend. Suggesting holding your positions but avoiding any large fresh manual lumpsums.",
            groww_link=groww_link,
        )

    return None


def check_fund_alerts(
    scheme_code: str,
    fund_name: str,
    history: list,
    current_nav: float,
    current_date: date,
    current_rsi: float | None,
    current_dist_52w: float | None,
    current_dist_200d_sma: float | None,
    rules: AlertRulesConfig,
) -> list[TriggeredAlert]:
    """Check today's indicators for a single fund against the 3-Tier boundaries."""
    alerts: list[TriggeredAlert] = []

    # 1. 3-Tier RSI Buy/Sell Signals
    if current_rsi is not None:
        if current_rsi <= rules.rsi_deep_oversold:
            alerts.append(TriggeredAlert(
                scheme_code=scheme_code,
                fund_name=fund_name,
                indicator_name="RSI (14)",
                current_value=current_rsi,
                trigger_level=rules.rsi_deep_oversold,
                alert_type="BUY TIER 3 / DEEP OVERSOLD",
                action_suggestion="Deploy Aggressive Lumpsum (Extreme Correction Bottom)."
            ))
        elif current_rsi <= rules.rsi_moderate_dip:
            alerts.append(TriggeredAlert(
                scheme_code=scheme_code,
                fund_name=fund_name,
                indicator_name="RSI (14)",
                current_value=current_rsi,
                trigger_level=rules.rsi_moderate_dip,
                alert_type="BUY TIER 2 / MODERATE DIP",
                action_suggestion="Deploy Moderate Lumpsum (Healthy Correction)."
            ))
        elif current_rsi <= rules.rsi_mild_pullback:
            alerts.append(TriggeredAlert(
                scheme_code=scheme_code,
                fund_name=fund_name,
                indicator_name="RSI (14)",
                current_value=current_rsi,
                trigger_level=rules.rsi_mild_pullback,
                alert_type="BUY TIER 1 / MILD PULLBACK",
                action_suggestion="Deploy Smaller Top-ups (Minor Pullback Support)."
            ))
        elif current_rsi >= rules.rsi_overbought:
            alerts.append(TriggeredAlert(
                scheme_code=scheme_code,
                fund_name=fund_name,
                indicator_name="RSI (14)",
                current_value=current_rsi,
                trigger_level=rules.rsi_overbought,
                alert_type="MOMENTUM WARNING / TRIM",
                action_suggestion="Pause Fresh Purchases / Trim Excess Allocation."
            ))

    # 2. 3-Tier 52-Week High Discount (Peak Pyramiding)
    if current_dist_52w is not None:
        if current_dist_52w <= rules.discount_deep_pct:
            alerts.append(TriggeredAlert(
                scheme_code=scheme_code,
                fund_name=fund_name,
                indicator_name="52W High Distance",
                current_value=current_dist_52w,
                trigger_level=rules.discount_deep_pct,
                alert_type="BUY TIER 3 / 52W DEEP CAPITULATION",
                action_suggestion="Deploy Aggressive Lumpsum (Generational Value Buying)."
            ))
        elif current_dist_52w <= rules.discount_moderate_pct:
            alerts.append(TriggeredAlert(
                scheme_code=scheme_code,
                fund_name=fund_name,
                indicator_name="52W High Distance",
                current_value=current_dist_52w,
                trigger_level=rules.discount_moderate_pct,
                alert_type="BUY TIER 2 / 52W MODERATE DISCOUNT",
                action_suggestion="Deploy Moderate Lumpsum (Solid Margin of Safety)."
            ))
        elif current_dist_52w <= rules.discount_mild_pct:
            alerts.append(TriggeredAlert(
                scheme_code=scheme_code,
                fund_name=fund_name,
                indicator_name="52W High Distance",
                current_value=current_dist_52w,
                trigger_level=rules.discount_mild_pct,
                alert_type="BUY TIER 1 / 52W MILD DISCOUNT",
                action_suggestion="Deploy Smaller Top-ups (Standard Retest Pullback)."
            ))

    # 3. 3-Tier 200D SMA Distance
    if current_dist_200d_sma is not None:
        if current_dist_200d_sma <= rules.sma_deep_capitulation_pct:
            alerts.append(TriggeredAlert(
                scheme_code=scheme_code,
                fund_name=fund_name,
                indicator_name="200D SMA Distance",
                current_value=current_dist_200d_sma,
                trigger_level=rules.sma_deep_capitulation_pct,
                alert_type="BUY TIER 3 / SMA DEEP CAPITULATION",
                action_suggestion="Deploy Aggressive Lumpsum (Severe Deviation Recovery Play)."
            ))
        elif current_dist_200d_sma <= rules.sma_moderate_discount_pct:
            alerts.append(TriggeredAlert(
                scheme_code=scheme_code,
                fund_name=fund_name,
                indicator_name="200D SMA Distance",
                current_value=current_dist_200d_sma,
                trigger_level=rules.sma_moderate_discount_pct,
                alert_type="BUY TIER 2 / SMA MODERATE DISCOUNT",
                action_suggestion="Deploy Moderate Lumpsum (Downtrend Accumulation)."
            ))
        elif abs(current_dist_200d_sma) <= rules.sma_trend_support_pct:
            alerts.append(TriggeredAlert(
                scheme_code=scheme_code,
                fund_name=fund_name,
                indicator_name="200D SMA Distance",
                current_value=current_dist_200d_sma,
                trigger_level=rules.sma_trend_support_pct,
                alert_type="BUY TIER 1 / SMA TREND SUPPORT",
                action_suggestion="Deploy Smaller Top-ups (Testing Critical Long-Term Support)."
            ))

    # 4. 200D SMA Trend Crossing Reversals
    if rules.enable_sma_crossing and len(history) >= 2:
        # history[1] is yesterday's publish point
        yesterday_point = history[1]
        yesterday_dist = distance_from_200d_sma(history[1:], yesterday_point.nav, yesterday_point.nav_date)
        if yesterday_dist is not None and current_dist_200d_sma is not None:
            # Bullish cross above
            if current_dist_200d_sma >= 0.0 and yesterday_dist < 0.0:
                alerts.append(TriggeredAlert(
                    scheme_code=scheme_code,
                    fund_name=fund_name,
                    indicator_name="200D SMA Trend Crossing",
                    current_value=current_dist_200d_sma,
                    trigger_level=0.0,
                    alert_type="BULLISH TREND CROSS-ABOVE",
                    action_suggestion="Trend Reversal Confirmed (Uptrend starting). Deploy Accumulations."
                ))
            # Bearish cross below
            elif current_dist_200d_sma <= 0.0 and yesterday_dist > 0.0:
                alerts.append(TriggeredAlert(
                    scheme_code=scheme_code,
                    fund_name=fund_name,
                    indicator_name="200D SMA Trend Crossing",
                    current_value=current_dist_200d_sma,
                    trigger_level=0.0,
                    alert_type="BEARISH TREND CROSS-BELOW",
                    action_suggestion="Trend Reversal Confirmed (Downtrend starting). Pause Fresh Buys."
                ))

    return alerts


def dispatch_alerts_email(
    alerts: list[TriggeredAlert],
    email_config: AlertEmailConfig,
    confluence_signals: list[DipBuyingSignal] | None = None,
    is_dev: bool = False,
    trimming_signals: list[TrimmingSignal] | None = None,
) -> bool:
    """Send a beautifully formatted HTML alert digest via SMTP."""
    if not email_config.enable:
        log.info("Email alerts are disabled in alerts.yaml. Skipping dispatch.")
        return False

    if not alerts and not confluence_signals and not trimming_signals:
        log.info("No technical indicators or briefings triggered today. Skipping alert email dispatch.")
        return False

    sender = email_config.sender_email
    receiver = email_config.receiver_email
    password = email_config.sender_password or os.getenv("EMAIL_PASSWORD", "")

    if not sender or not receiver:
        log.warning("Email dispatcher skipped: sender_email or receiver_email is empty.")
        return False

    if not password:
        log.warning(
            "Email dispatcher skipped: SMTP password not configured in alerts.yaml "
            "and EMAIL_PASSWORD environment variable is empty."
        )
        return False

    # Create the HTML structure
    msg = MIMEMultipart("alternative")
    subject_prefix = "🚨 [DEV]" if is_dev else "🚨"
    msg["Subject"] = f"{subject_prefix} MFHelper Technical Buy/Sell Alerts: {len(alerts)} Trigger(s)"
    msg["From"] = sender
    msg["To"] = receiver

    briefing_html = ""
    if confluence_signals:
        briefing_html += """
        <div style="background-color: #fdfefe; border: 1px solid #c3e6cb; border-radius: 6px; padding: 20px; margin-bottom: 25px; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">
            <h3 style="color: #155724; margin-top: 0; display: flex; align-items: center; gap: 8px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
               🚨 PORTFOLIO DIP-BUYING INTELLIGENCE BRIEFING
            </h3>
            <div style="display: flex; flex-direction: column; gap: 15px; width: 100%;">
        """
        for sig in confluence_signals:
            if sig.tier == 3:
                badge = '<span style="background-color: #f8d7da; color: #721c24; padding: 4px 10px; border-radius: 4px; font-weight: bold; font-size: 11px; display: inline-block;">BUY TIER 3 (STRONG)</span>'
                border_color = "#f5c6cb"
                card_bg = "#fdf3f2"
            elif sig.tier == 2:
                badge = '<span style="background-color: #fff3cd; color: #856404; padding: 4px 10px; border-radius: 4px; font-weight: bold; font-size: 11px; display: inline-block;">BUY TIER 2 (MODERATE)</span>'
                border_color = "#ffeeba"
                card_bg = "#fffdf0"
            else:
                badge = '<span style="background-color: #d1ecf1; color: #0c5460; padding: 4px 10px; border-radius: 4px; font-weight: bold; font-size: 11px; display: inline-block;">BUY TIER 1 (MILD)</span>'
                border_color = "#bee5eb"
                card_bg = "#f4fafd"
                
            reasons_str = ", ".join(sig.reasons)
            briefing_html += f"""
                <div style="border: 1px solid {border_color}; background-color: {card_bg}; padding: 15px; border-radius: 6px; margin-bottom: 12px;">
                    <div style="margin-bottom: 8px;">
                        <span style="font-weight: bold; font-size: 15px; color: #212529; vertical-align: middle; margin-right: 8px;">{sig.fund_name}</span>
                        {badge}
                    </div>
                    <div style="font-size: 12px; color: #6c757d; line-height: 1.4; margin-bottom: 6px;">
                        <strong>Triggered by confluences:</strong> {reasons_str}
                    </div>
                    <div style="font-size: 13px; color: #212529; line-height: 1.5; margin-top: 6px; font-style: italic;">
                        <strong>Action Suggestion:</strong> {sig.suggestion}
                    </div>
                    <div style="margin-top: 12px;">
                        <a href="{sig.groww_link}" target="_blank" style="background-color: #155724; color: #ffffff; padding: 6px 14px; border-radius: 4px; text-decoration: none; font-size: 12px; font-weight: bold; display: inline-block;">
                            🛒 BUY ON GROWW
                        </a>
                    </div>
                </div>
            """
        briefing_html += """
            </div>
        </div>
        """

    if trimming_signals:
        briefing_html += """
        <div style="background-color: #fffaf0; border: 1px solid #f5c6cb; border-radius: 6px; padding: 20px; margin-bottom: 25px; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">
            <h3 style="color: #721c24; margin-top: 0; display: flex; align-items: center; gap: 8px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
               🚨 PORTFOLIO PROFIT-TAKING & TRIMMING BRIEFING
            </h3>
            <div style="display: flex; flex-direction: column; gap: 15px; width: 100%;">
        """
        for sig in trimming_signals:
            if sig.tier == 3:
                badge = '<span style="background-color: #f8d7da; color: #721c24; padding: 4px 10px; border-radius: 4px; font-weight: bold; font-size: 11px; display: inline-block;">TRIM TIER 3 (URGENT)</span>'
                border_color = "#f5c6cb"
                card_bg = "#fdf3f2"
            elif sig.tier == 2:
                badge = '<span style="background-color: #ffe8cc; color: #7a3700; padding: 4px 10px; border-radius: 4px; font-weight: bold; font-size: 11px; display: inline-block;">TRIM TIER 2 (MODERATE)</span>'
                border_color = "#ffd8a8"
                card_bg = "#fff9db"
            else:
                badge = '<span style="background-color: #fff3cd; color: #856404; padding: 4px 10px; border-radius: 4px; font-weight: bold; font-size: 11px; display: inline-block;">TRIM TIER 1 (MILD)</span>'
                border_color = "#ffeeba"
                card_bg = "#fffdf0"
                
            reasons_str = ", ".join(sig.reasons)
            briefing_html += f"""
                <div style="border: 1px solid {border_color}; background-color: {card_bg}; padding: 15px; border-radius: 6px; margin-bottom: 12px;">
                    <div style="margin-bottom: 8px;">
                        <span style="font-weight: bold; font-size: 15px; color: #212529; vertical-align: middle; margin-right: 8px;">{sig.fund_name}</span>
                        {badge}
                    </div>
                    <div style="font-size: 12px; color: #6c757d; line-height: 1.4; margin-bottom: 6px;">
                        <strong>Triggered by confluences:</strong> {reasons_str}
                    </div>
                    <div style="font-size: 13px; color: #212529; line-height: 1.5; margin-top: 6px; font-style: italic;">
                        <strong>Action Suggestion:</strong> {sig.suggestion}
                    </div>
                    <div style="margin-top: 12px;">
                        <a href="{sig.groww_link}" target="_blank" style="background-color: #721c24; color: #ffffff; padding: 6px 14px; border-radius: 4px; text-decoration: none; font-size: 12px; font-weight: bold; display: inline-block;">
                            🛒 TRIM ON GROWW
                        </a>
                    </div>
                </div>
            """
        briefing_html += """
            </div>
        </div>
        """

    rows_html = ""
    for alt in alerts:
        # Determine background color based on alert type
        bg_color = "#EBF2FF"  # Blue default
        text_color = "#004085"
        if "BUY TIER 3" in alt.alert_type:
            bg_color = "#D4EDDA"  # Light green
            text_color = "#155724"
        elif "BUY TIER 2" in alt.alert_type:
            bg_color = "#D1E7DD"  # Slightly lighter green
            text_color = "#0F5132"
        elif "BUY TIER 1" in alt.alert_type:
            bg_color = "#E8F5E9"  # Soft mint green
            text_color = "#2E7D32"
        elif "CROSS-ABOVE" in alt.alert_type:
            bg_color = "#E2F0D9"  # Lime soft green
            text_color = "#385723"
        elif "CROSS-BELOW" in alt.alert_type or "WARNING" in alt.alert_type:
            bg_color = "#F8D7DA"  # Soft red
            text_color = "#721C24"

        value_suffix = "%" if "Distance" in alt.indicator_name or "Crossing" in alt.indicator_name else ""
        trigger_suffix = "%" if "Distance" in alt.indicator_name else ""

        rows_html += f"""
        <tr style="background-color: {bg_color}; color: {text_color};">
            <td style="padding: 10px; border: 1px solid #dee2e6; font-weight: bold;">{alt.fund_name} ({alt.scheme_code})</td>
            <td style="padding: 10px; border: 1px solid #dee2e6;">{alt.indicator_name}</td>
            <td style="padding: 10px; border: 1px solid #dee2e6; font-weight: bold;">{alt.current_value:.2f}{value_suffix}</td>
            <td style="padding: 10px; border: 1px solid #dee2e6;">{alt.alert_type}</td>
            <td style="padding: 10px; border: 1px solid #dee2e6; font-style: italic;">{alt.action_suggestion}</td>
        </tr>
        """

    table_html = ""
    if alerts:
        table_html = f"""
            <table style="width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 14px;">
                <thead>
                    <tr style="background-color: #343a40; color: #ffffff; text-align: left;">
                        <th style="padding: 12px 10px; border: 1px solid #343a40;">Fund Name</th>
                        <th style="padding: 12px 10px; border: 1px solid #343a40;">Indicator</th>
                        <th style="padding: 12px 10px; border: 1px solid #343a40;">Current Value</th>
                        <th style="padding: 12px 10px; border: 1px solid #343a40;">Alert Triggered</th>
                        <th style="padding: 12px 10px; border: 1px solid #343a40;">Suggested Action</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        """
    else:
        table_html = """
            <div style="background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 15px; border-radius: 6px; text-align: center; color: #6c757d; font-size: 13px; margin-top: 20px; font-style: italic;">
                All active indicators have been consolidated into your top-level Intelligence Briefing cards above!
            </div>
        """

    html_content = f"""
    <html>
    <head>
        <meta charset="utf-8">
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8f9fa; padding: 20px;">
        <div style="max-width: 800px; margin: 0 auto; background: #ffffff; padding: 25px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border: 1px solid #dee2e6;">
            <h2 style="color: #212529; border-bottom: 2px solid #dee2e6; padding-bottom: 15px; margin-top: 0;">📈 MFHelper Technical Indicator Alerts</h2>
            <p style="color: #495057; line-height: 1.6;">
                The daily NAV scheduler has successfully completed. Below are the mutual funds that have broken configured technical support levels or buy/sell zones today:
            </p>
            {briefing_html}
            {table_html}
            <p style="color: #6c757d; font-size: 11px; margin-top: 30px; border-top: 1px solid #dee2e6; padding-top: 15px; line-height: 1.5;">
                This message was auto-generated by the daily scheduled task of your local MFHelper project. 
                Alert thresholds and triggers are fully configurable inside your local <code>config/alerts.yaml</code> settings.
            </p>
        </div>
    </body>
    </html>
    """

    msg.attach(MIMEText(html_content, "html"))

    try:
        log.info("Connecting to SMTP server %s:%d ...", email_config.smtp_server, email_config.smtp_port)
        with smtplib.SMTP(email_config.smtp_server, email_config.smtp_port, timeout=15) as server:
            if email_config.use_tls:
                server.starttls()
            server.login(sender, password)
            server.sendmail(sender, receiver, msg.as_string())
        log.info("Technical Alert email successfully dispatched to %s", receiver)
        return True
    except Exception as e:
        log.exception("Failed to send Technical Alert email via SMTP:")
        return False


def resolve_conflicting_alerts(alerts: list[TriggeredAlert]) -> list[TriggeredAlert]:
    """Identify and resolve contradictory BUY and TRIM/WARNING alerts for any fund."""
    from collections import defaultdict
    by_fund = defaultdict(list)
    for alt in alerts:
        by_fund[alt.scheme_code].append(alt)
        
    resolved_alerts = []
    
    for code, fund_alerts in by_fund.items():
        has_buy = any("BUY" in alt.alert_type for alt in fund_alerts)
        has_sell = any("TRIM" in alt.alert_type or "WARNING" in alt.alert_type or "CROSS-BELOW" in alt.alert_type for alt in fund_alerts)
        
        if has_buy and has_sell:
            # We have a contradiction!
            # Find the RSI value and Discount value
            rsi_alt = next((alt for alt in fund_alerts if "RSI" in alt.indicator_name), None)
            disc_alt = next((alt for alt in fund_alerts if "Distance" in alt.indicator_name), None)
            
            fund_name = fund_alerts[0].fund_name
            rsi_val_str = f"{rsi_alt.current_value:.2f}" if rsi_alt else "n/a"
            disc_val_str = f"{disc_alt.current_value:.2f}%" if disc_alt else "n/a"
            
            # Create a single, consolidated warning alert
            resolved_alerts.append(TriggeredAlert(
                scheme_code=code,
                fund_name=fund_name,
                indicator_name="RSI vs. Peak Discount",
                current_value=rsi_alt.current_value if rsi_alt else (disc_alt.current_value if disc_alt else 0.0),
                trigger_level=rsi_alt.trigger_level if rsi_alt else 0.0,
                alert_type="CONTRADICTORY INDICATORS / HOLD",
                action_suggestion=f"Consolidating: Short-term momentum is extremely high (RSI is {rsi_val_str}), but the fund remains at a long-term discount ({disc_val_str}). Suggesting holding off on lumpsums and pausing fresh buys until RSI cools down."
            ))
            
            # Keep any trend crossing alerts or other non-conflicting alerts if present
            for alt in fund_alerts:
                if "RSI" not in alt.indicator_name and "Distance" not in alt.indicator_name:
                    resolved_alerts.append(alt)
        else:
            # No contradiction, keep all alerts for this fund
            resolved_alerts.extend(fund_alerts)
            
    return resolved_alerts
