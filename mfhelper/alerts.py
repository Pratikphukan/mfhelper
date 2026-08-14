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
) -> bool:
    """Send a beautifully formatted HTML alert digest via SMTP."""
    if not email_config.enable:
        log.info("Email alerts are disabled in alerts.yaml. Skipping dispatch.")
        return False

    if not alerts:
        log.info("No technical indicators triggered today. Skipping alert email dispatch.")
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
    msg["Subject"] = f"🚨 MFHelper Technical Buy/Sell Alerts: {len(alerts)} Trigger(s)"
    msg["From"] = sender
    msg["To"] = receiver

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
