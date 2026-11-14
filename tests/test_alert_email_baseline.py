"""Golden-file check that the alert email is unchanged when no regime context is supplied.

Regenerate the fixture only for an intentional email redesign:
    UPDATE_EMAIL_BASELINE=1 pytest tests/test_alert_email_baseline.py
"""

from email import message_from_string
import os
from pathlib import Path

import pytest

from mfhelper import alerts
from mfhelper.alerts import DipBuyingSignal, TriggeredAlert, TrimmingSignal
from mfhelper.config import AlertEmailConfig

FIXTURE = Path(__file__).parent / "fixtures" / "alert_email_baseline.html"


class FakeSMTP:
    sent: list[str] = []

    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def starttls(self):
        pass

    def login(self, *_args):
        pass

    def sendmail(self, _sender, _receiver, message):
        FakeSMTP.sent.append(message)


def _email_config() -> AlertEmailConfig:
    return AlertEmailConfig(
        enable=True,
        smtp_server="smtp.example.com",
        smtp_port=587,
        use_tls=True,
        sender_email="sender@example.com",
        sender_password="not-a-real-password",
        receiver_email="receiver@example.com",
    )


def sample_inputs():
    triggered = [
        TriggeredAlert("100001", "Example Flexi Cap Direct Growth", "RSI (14)", 31.2, 35.0,
                       "BUY TIER 3 / DEEP OVERSOLD", "Deploy Aggressive Lumpsum (Extreme Correction Bottom)."),
        TriggeredAlert("100002", "Example Mid Cap Direct Growth", "52W High Distance", -6.1, -5.0,
                       "BUY TIER 1 / 52W MILD DISCOUNT", "Deploy Smaller Top-ups (Standard Retest Pullback)."),
        TriggeredAlert("100003", "Example Large Cap Direct Growth", "RSI (14)", 74.0, 70.0,
                       "MOMENTUM WARNING / TRIM", "Pause Fresh Purchases / Trim Excess Allocation."),
    ]
    confluence = [
        DipBuyingSignal("100001", "Example Flexi Cap Direct Growth", 3,
                        ["RSI is 31.20 (Deeply Oversold)", "52W Drop is -22.00% (Deep Discount)"],
                        "Strong Confluence Buy. Fund is highly oversold and deeply discounted from peak. Suggesting aggressive lumpsum top-up.",
                        "https://groww.in/mutual-funds/jm-flexi-cap-fund-direct-growth"),
        DipBuyingSignal("100002", "Example Mid Cap Direct Growth", 1,
                        ["RSI is 52.00 (Mild Pullback)", "52W Drop is -6.10% (Mild Discount)"],
                        "Mild Confluence Pullback. Healthy consolidation. Suggesting standard top-up.",
                        "https://groww.in/mutual-funds/motilal-oswal-most-focused-midcap-30-fund-direct-growth"),
    ]
    trimming = [
        TrimmingSignal("100003", "Example Large Cap Direct Growth", 2,
                       ["RSI is 72.00 (Standard Overbought)", "52W Drop is -1.50% (Near Peak)"],
                       "Moderate Overstretch. Strong uptrend momentum, but entering the trim zone.",
                       "https://groww.in/mutual-funds/axis-multicap-fund-direct-growth"),
    ]
    return triggered, confluence, trimming


def render_baseline_html(monkeypatch, **extra_kwargs) -> str:
    FakeSMTP.sent = []
    monkeypatch.setattr(alerts.smtplib, "SMTP", FakeSMTP)
    triggered, confluence, trimming = sample_inputs()
    sent = alerts.dispatch_alerts_email(
        triggered, _email_config(), confluence, is_dev=True, trimming_signals=trimming, **extra_kwargs
    )
    assert sent is True
    message = message_from_string(FakeSMTP.sent[0])
    html_part = next(part for part in message.walk() if part.get_content_type() == "text/html")
    return html_part.get_payload(decode=True).decode("utf-8")


def test_email_html_matches_pre_regime_baseline(monkeypatch):
    html = render_baseline_html(monkeypatch)

    if os.environ.get("UPDATE_EMAIL_BASELINE") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(html, encoding="utf-8")
    assert html == FIXTURE.read_text(encoding="utf-8")


# --- regime additions -----------------------------------------------------------------


def _regime_context():
    from mfhelper.market_regime import MarketContext, Regime, Valuation

    return MarketContext(
        available=True, regime=Regime.CORRECTION, valuation=Valuation(26.0, "stretched", source="nse"),
        vix_avg=19.4, index_close=21000.0, sma_long=20000.0,
    )


def test_banner_is_added_without_touching_the_rest(monkeypatch):
    baseline = FIXTURE.read_text(encoding="utf-8")
    html = render_baseline_html(monkeypatch, market_context=_regime_context())

    assert "Market regime: CORRECTION" in html and "P/E 26.0 (stretched)" in html
    start = html.index('<p style="margin:0 0 12px 0')
    banner = html[start : html.index("</p>", start) + 4]
    assert html.replace(banner, "") == baseline


def test_alert_row_note_is_rendered_and_escaped(monkeypatch):
    from dataclasses import replace

    triggered, confluence, trimming = sample_inputs()
    triggered[1] = replace(triggered[1], context_note="Market is volatile. <b>wait</b>")
    monkeypatch.setattr(alerts.smtplib, "SMTP", FakeSMTP)
    FakeSMTP.sent = []
    alerts.dispatch_alerts_email(triggered, _email_config(), confluence, is_dev=True, trimming_signals=trimming)
    message = message_from_string(FakeSMTP.sent[0])
    html = next(p for p in message.walk() if p.get_content_type() == "text/html").get_payload(decode=True).decode()
    assert "Market is volatile. &lt;b&gt;wait&lt;/b&gt;" in html
    assert html.count("Market is volatile") == 1  # only the one row that has a note


def test_multiplier_and_note_appear_on_the_buy_card_only(monkeypatch):
    from dataclasses import replace

    triggered, confluence, trimming = sample_inputs()
    confluence[0] = replace(confluence[0], multiplier=1.875, context_note="Nifty 50 P/E 17.0 < 18: x1.25 <b>")
    monkeypatch.setattr(alerts.smtplib, "SMTP", FakeSMTP)
    FakeSMTP.sent = []
    alerts.dispatch_alerts_email(triggered, _email_config(), confluence, is_dev=True, trimming_signals=trimming)
    message = message_from_string(FakeSMTP.sent[0])
    html = next(p for p in message.walk() if p.get_content_type() == "text/html").get_payload(decode=True).decode()
    assert "Suggested size:</strong> 1.88x your normal top-up" in html
    assert "x1.25 &lt;b&gt;" in html  # escaped
    assert html.count("Suggested size:") == 1


def test_trim_context_note_is_rendered(monkeypatch):
    from dataclasses import replace

    triggered, confluence, trimming = sample_inputs()
    trimming[0] = replace(trimming[0], context_note="Fired earlier than usual: P/E 25 > 24")
    monkeypatch.setattr(alerts.smtplib, "SMTP", FakeSMTP)
    FakeSMTP.sent = []
    alerts.dispatch_alerts_email(triggered, _email_config(), confluence, is_dev=True, trimming_signals=trimming)
    message = message_from_string(FakeSMTP.sent[0])
    html = next(p for p in message.walk() if p.get_content_type() == "text/html").get_payload(decode=True).decode()
    assert "Fired earlier than usual: P/E 25 &gt; 24" in html


def test_a_banner_alone_never_triggers_an_email(monkeypatch):
    FakeSMTP.sent = []
    monkeypatch.setattr(alerts.smtplib, "SMTP", FakeSMTP)
    sent = alerts.dispatch_alerts_email([], _email_config(), [], is_dev=True, trimming_signals=[],
                                        market_context=_regime_context())
    assert sent is False and FakeSMTP.sent == []


@pytest.mark.parametrize("value,text", [(1.0, "1x"), (1.5, "1.5x"), (2.0, "2x"), (0.75, "0.75x"), (1.875, "1.88x"), (0.5, "0.5x")])
def test_format_multiplier(value, text):
    assert alerts.format_multiplier(value) == text
