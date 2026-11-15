from dataclasses import replace
from datetime import date
import itertools

import pytest

from mfhelper.alerts import DipBuyingSignal, TriggeredAlert, check_trimming_signal
from mfhelper.config import AlertRulesConfig, RegimeSettings
from mfhelper.market_regime import MarketContext, Regime, Valuation
from mfhelper import regime_filter as rf

CFG = RegimeSettings(enable=True)
RULES = AlertRulesConfig(
    rsi_mild_pullback=55.0, rsi_moderate_dip=45.0, rsi_deep_oversold=35.0, rsi_overbought=70.0,
    sma_trend_support_pct=2.0, sma_moderate_discount_pct=-2.0, sma_deep_capitulation_pct=-10.0,
    discount_mild_pct=-5.0, discount_moderate_pct=-10.0, discount_deep_pct=-20.0, enable_sma_crossing=True,
)
FAIR = Valuation(22.0, "fair", source="nse", as_of=date(2026, 11, 6))
CHEAP = Valuation(17.0, "cheap", source="nse", as_of=date(2026, 11, 6))
STRETCHED = Valuation(25.0, "stretched", source="nse", as_of=date(2026, 11, 6))


def ctx(regime: Regime, valuation: Valuation = FAIR, available: bool = True) -> MarketContext:
    return MarketContext(available=available, regime=regime, valuation=valuation)


def alert(alert_type: str, indicator: str = "RSI (14)") -> TriggeredAlert:
    return TriggeredAlert("100", "Fund A", indicator, 30.0, 35.0, alert_type, "do it")


def signal(tier: int) -> DipBuyingSignal:
    return DipBuyingSignal("100", "Fund A", tier, ["r1", "r2"], "buy", "https://groww.in/x")


def annotate(regime, alerts=(), confluence=None, rsi=40.0, dist_200d=-5.0, valuation=FAIR, cfg=CFG, vix_avg=20.0):
    context = MarketContext(available=True, regime=regime, valuation=valuation, vix_avg=vix_avg)
    return rf.annotate_buys(
        context, cfg, rsi=rsi, dist_200d_sma=dist_200d, alerts=list(alerts), confluence=confluence,
    )


T1 = alert("BUY TIER 1 / MILD PULLBACK")
T2 = alert("BUY TIER 2 / MODERATE DIP")
T3 = alert("BUY TIER 3 / DEEP OVERSOLD")
CROSS_UP = alert("BULLISH TREND CROSS-ABOVE", "200D SMA Trend Crossing")
CROSS_DOWN = alert("BEARISH TREND CROSS-BELOW", "200D SMA Trend Crossing")
TRIM = alert("MOMENTUM WARNING / TRIM")
ALL_ALERTS = [T1, T2, T3, CROSS_UP, CROSS_DOWN, TRIM]


# --- the safety property: advice never removes anything ---------------------------------


@pytest.mark.parametrize("regime", list(Regime))
@pytest.mark.parametrize("valuation", [FAIR, CHEAP, STRETCHED, Valuation(None, "unknown")])
def test_every_alert_and_signal_survives_in_every_regime(regime, valuation):
    for rsi, dist, tier in itertools.product([None, 10.0, 25.0, 31.0, 50.0], [None, -30.0, -12.0, -5.0, 3.0], [None, 1, 2, 3]):
        alerts, confluence = annotate(
            regime, ALL_ALERTS, signal(tier) if tier else None, rsi=rsi, dist_200d=dist, valuation=valuation
        )
        assert [(a.scheme_code, a.indicator_name, a.current_value, a.alert_type) for a in alerts] == [
            (a.scheme_code, a.indicator_name, a.current_value, a.alert_type) for a in ALL_ALERTS
        ]  # same technical alerts, in the same order
        assert (confluence.tier if confluence else None) == tier


def test_annotation_only_changes_advice_fields_and_never_suggests_size():
    for regime in Regime:
        alerts, confluence = annotate(regime, ALL_ALERTS, signal(2), rsi=22.0, dist_200d=-15.0)
        for before, after in zip(ALL_ALERTS, alerts):
            assert (after.scheme_code, after.indicator_name, after.current_value, after.alert_type) == (
                before.scheme_code, before.indicator_name, before.current_value, before.alert_type
            )
        assert confluence.multiplier is None


def test_alerts_that_are_not_buys_never_get_a_note():
    for regime in Regime:
        alerts, _ = annotate(regime, [CROSS_UP, CROSS_DOWN, TRIM], None, rsi=22.0, dist_200d=-15.0)
        assert [a.context_note for a in alerts] == ["", "", ""]


def test_no_confluence_stays_no_confluence():
    assert annotate(Regime.BEAR, [T3], None)[1] is None


# --- notes by regime --------------------------------------------------------------------


def test_neutral_labels_signal_as_technical_and_suggests_no_amount():
    alerts, confluence = annotate(Regime.NEUTRAL, [T1, T3], signal(2))
    assert [a.display_label for a in alerts] == ["TECHNICAL DIP TIER 1", "TECHNICAL DIP TIER 3"]
    assert confluence.display_label == "TECHNICAL DIP TIER 2"
    assert "no amount" in confluence.suggestion
    assert confluence.multiplier is None


def test_unavailable_context_behaves_like_neutral():
    context = MarketContext(False, Regime.NEUTRAL, FAIR)
    alerts, confluence = rf.annotate_buys(
        context, CFG, rsi=20.0, dist_200d_sma=-30.0, alerts=[T1, T3], confluence=signal(3)
    )
    assert [a.display_label for a in alerts] == ["TECHNICAL DIP TIER 1", "TECHNICAL DIP TIER 3"]
    assert "unavailable" in confluence.context_note
    assert confluence.multiplier is None


def test_uptrend_shows_technical_signal_without_size():
    alerts, confluence = annotate(Regime.UPTREND, [T1, T2, T3, TRIM], signal(1))
    assert [a.display_label for a in alerts[:3]] == [
        "TECHNICAL DIP TIER 1", "TECHNICAL DIP TIER 2", "TECHNICAL DIP TIER 3",
    ]
    assert alerts[3] == TRIM
    assert "UPTREND" in confluence.context_note
    assert confluence.multiplier is None


def test_correction_labels_tier_1_watch_and_tier_2_3_review():
    alerts, confluence = annotate(Regime.CORRECTION, [T1, T2, T3], signal(1), vix_avg=19.44)
    assert alerts[0].display_label == "WATCH · TECHNICAL DIP TIER 1"
    assert alerts[1].display_label == "REVIEW SIGNAL · TECHNICAL DIP TIER 2"
    assert alerts[2].display_label == "REVIEW SIGNAL · TECHNICAL DIP TIER 3"
    assert "VIX is 19.4" in alerts[0].context_note
    assert "Tier 2 or 3" in alerts[0].action_suggestion
    assert confluence.display_label == "WATCH · TECHNICAL DIP TIER 1"
    assert confluence.multiplier is None

    _, stronger = annotate(Regime.CORRECTION, [], signal(3))
    assert stronger.display_label == "REVIEW SIGNAL · TECHNICAL DIP TIER 3"


def test_correction_note_works_without_vix_number():
    alerts, _ = annotate(Regime.CORRECTION, [T1], None, vix_avg=None)
    assert "volatility is elevated" in alerts[0].context_note


def test_bear_marks_non_capitulation_as_watch_without_predicting_the_fund():
    alerts, confluence = annotate(Regime.BEAR, [T1, T2, T3], signal(3), rsi=31.2, dist_200d=-8.4)
    for a in alerts:
        assert a.display_label.startswith("DIP DETECTED — WATCH")
        assert "does not predict the fund's next move" in a.action_suggestion
        assert "thresholds not met" in a.context_note
    assert confluence.display_label.startswith("DIP DETECTED — WATCH")
    assert "does not predict" in confluence.suggestion
    assert confluence.multiplier is None


def test_bear_tags_capitulation_with_the_real_numbers():
    alerts, confluence = annotate(Regime.BEAR, [T1, T3, CROSS_UP], signal(3), rsi=22.0, dist_200d=-13.5)
    assert alerts[0].display_label.startswith("CAPITULATION DETECTED — REVIEW BEFORE DECIDING")
    assert "not proof the fund has bottomed" in alerts[0].action_suggestion
    assert "RSI 22.0 <= 25" in alerts[0].context_note and "-13.5% <= -12%" in alerts[0].context_note
    assert alerts[1].display_label.startswith("CAPITULATION DETECTED — REVIEW BEFORE DECIDING")
    assert alerts[2].context_note == ""  # not a BUY TIER alert
    assert confluence.display_label.startswith("CAPITULATION DETECTED — REVIEW BEFORE DECIDING")
    assert confluence.multiplier is None


@pytest.mark.parametrize(
    "rsi,dist,expected",
    [
        (25.0, -12.0, True),      # both boundaries inclusive
        (25.01, -12.0, False),
        (25.0, -11.99, False),
        (10.0, -11.0, False),     # one condition is not enough
        (40.0, -30.0, False),
        (None, -30.0, False),     # missing data never qualifies
        (10.0, None, False),
    ],
)
def test_capitulation_requires_both_conditions(rsi, dist, expected):
    assert rf.meets_capitulation(rsi, dist, CFG) is expected


def test_bear_missing_indicators_give_watch_label_and_explain_missing_data():
    alerts, _ = annotate(Regime.BEAR, [T3], None, rsi=None, dist_200d=None)
    assert alerts[0].display_label.startswith("DIP DETECTED — WATCH")
    assert "RSI is unavailable" in alerts[0].context_note
    assert "200D SMA distance is unavailable" in alerts[0].context_note


def test_bear_capitulation_thresholds_are_configurable():
    cfg = replace(CFG, capitulation_rsi=30.0, capitulation_sma_discount_pct=-8.0)
    alerts, _ = annotate(Regime.BEAR, [T3], None, rsi=29.0, dist_200d=-9.0, cfg=cfg)
    assert alerts[0].display_label.startswith("CAPITULATION DETECTED — REVIEW BEFORE DECIDING")
    warn, _ = annotate(Regime.BEAR, [T3], None, rsi=31.0, dist_200d=-9.0, cfg=cfg)
    assert "RSI 31.0 is above 30" in warn[0].context_note
    assert "200D SMA distance" not in warn[0].context_note  # This threshold is met.


@pytest.mark.parametrize("regime", list(Regime))
def test_configured_multipliers_are_not_attached_in_any_regime(regime):
    cfg = replace(CFG, multiplier_tier2=2.5, multiplier_cheap_factor=2.0)
    out = annotate(regime, [], signal(2), valuation=CHEAP, cfg=cfg)[1]
    assert out.multiplier is None
    assert "normal top-up" not in out.suggestion
    assert "Sizing:" not in out.context_note


def test_buy_tier_parsing():
    assert [rf.buy_tier(a) for a in (T1, T2, T3, CROSS_UP, TRIM, CROSS_DOWN)] == [1, 2, 3, None, None, None]


# --- trimming -------------------------------------------------------------------------


def trim(valuation, rsi, dist):
    return rf.check_trimming_for_context(
        ctx(Regime.BEAR, valuation), CFG, scheme_code="100", fund_name="Fund A", rsi=rsi, dist_52w=dist, rules=RULES,
    )


@pytest.mark.parametrize(
    "valuation",
    [FAIR, CHEAP, Valuation(None, "unknown"), Valuation(25.0, "stretched", source="manual")],
)
def test_trimming_is_unchanged_unless_live_valuation_is_stretched(valuation):
    for rsi, dist in [(62.0, -6.5), (66.0, -4.0), (72.0, -1.5), (80.0, -0.5), (50.0, -10.0)]:
        assert trim(valuation, rsi, dist) == check_trimming_signal("100", "Fund A", rsi, dist, RULES)


def test_stretched_valuation_makes_trims_fire_earlier():
    assert check_trimming_signal("100", "Fund A", 62.0, -6.5, RULES) is None
    out = trim(STRETCHED, 62.0, -6.5)  # RSI >= 60 and 52W >= -7
    assert out.tier == 1 and "Fired earlier than usual" in out.context_note
    assert "P/E 25.0 > 24" in out.context_note and "-5" in out.context_note and "+2" in out.context_note


def test_stretched_valuation_can_raise_the_tier():
    standard = check_trimming_signal("100", "Fund A", 72.0, -1.5, RULES)
    out = trim(STRETCHED, 72.0, -1.5)
    assert (standard.tier, out.tier) == (2, 3) and out.context_note


def test_no_note_when_the_signal_would_have_fired_anyway():
    out = trim(STRETCHED, 80.0, -0.5)
    assert out.tier == 3 and out.context_note == ""


def test_stretched_valuation_still_needs_both_conditions():
    assert trim(STRETCHED, 80.0, -15.0) is None
    assert trim(STRETCHED, 50.0, -0.5) is None
    assert trim(STRETCHED, None, -0.5) is None


def test_trim_offsets_are_configurable_and_reason_text_shows_real_values():
    cfg = replace(CFG, trim_rsi_offset=10.0, trim_52w_offset_pts=0.0)
    out = rf.check_trimming_for_context(
        ctx(Regime.NEUTRAL, STRETCHED), cfg, scheme_code="100", fund_name="Fund A", rsi=57.0, dist_52w=-4.0, rules=RULES,
    )
    assert out.tier == 1 and any("RSI is 57.00" in r for r in out.reasons)


def test_regime_never_changes_trims_by_itself():
    for regime in Regime:
        out = rf.check_trimming_for_context(
            ctx(regime), CFG, scheme_code="100", fund_name="Fund A", rsi=80.0, dist_52w=-0.5, rules=RULES,
        )
        assert out is not None and out.tier == 3
