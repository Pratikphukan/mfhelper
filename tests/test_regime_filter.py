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


def strip_notes(alerts):
    return [replace(a, context_note="") for a in alerts]


@pytest.mark.parametrize("regime", list(Regime))
@pytest.mark.parametrize("valuation", [FAIR, CHEAP, STRETCHED, Valuation(None, "unknown")])
def test_every_alert_and_signal_survives_in_every_regime(regime, valuation):
    for rsi, dist, tier in itertools.product([None, 10.0, 25.0, 31.0, 50.0], [None, -30.0, -12.0, -5.0, 3.0], [None, 1, 2, 3]):
        alerts, confluence = annotate(
            regime, ALL_ALERTS, signal(tier) if tier else None, rsi=rsi, dist_200d=dist, valuation=valuation
        )
        assert strip_notes(alerts) == ALL_ALERTS  # same alerts, same order, nothing added or removed
        assert (confluence.tier if confluence else None) == tier


def test_only_the_note_and_size_fields_ever_change():
    for regime in Regime:
        alerts, confluence = annotate(regime, ALL_ALERTS, signal(2), rsi=22.0, dist_200d=-15.0)
        for before, after in zip(ALL_ALERTS, alerts):
            assert replace(after, context_note="") == before
        assert replace(confluence, multiplier=None, context_note="") == signal(2)


def test_alerts_that_are_not_buys_never_get_a_note():
    for regime in Regime:
        alerts, _ = annotate(regime, [CROSS_UP, CROSS_DOWN, TRIM], None, rsi=22.0, dist_200d=-15.0)
        assert [a.context_note for a in alerts] == ["", "", ""]


def test_no_confluence_stays_no_confluence():
    assert annotate(Regime.BEAR, [T3], None)[1] is None


# --- notes by regime --------------------------------------------------------------------


def test_neutral_adds_no_regime_note():
    alerts, confluence = annotate(Regime.NEUTRAL, [T1, T3], signal(2))
    assert [a.context_note for a in alerts] == ["", ""]
    assert confluence.context_note == ""


def test_unavailable_context_behaves_like_neutral():
    context = MarketContext(False, Regime.NEUTRAL, FAIR)
    alerts, confluence = rf.annotate_buys(
        context, CFG, rsi=20.0, dist_200d_sma=-30.0, alerts=[T1, T3], confluence=signal(3)
    )
    assert [a.context_note for a in alerts] == ["", ""] and confluence.context_note == ""


def test_uptrend_note_is_added_to_every_buy():
    alerts, confluence = annotate(Regime.UPTREND, [T1, T2, T3, TRIM], signal(1))
    notes = [a.context_note for a in alerts]
    assert all("uptrend" in n for n in notes[:3]) and notes[3] == ""
    assert "uptrend" in confluence.context_note


def test_correction_flags_tier_1_only():
    alerts, confluence = annotate(Regime.CORRECTION, [T1, T2, T3], signal(1), vix_avg=19.44)
    assert "Tier-1 dips are weaker" in alerts[0].context_note and "VIX avg 19.4" in alerts[0].context_note
    assert alerts[1].context_note == "" and alerts[2].context_note == ""
    assert "wait for Tier 2 or 3" in confluence.context_note
    assert annotate(Regime.CORRECTION, [], signal(2))[1].context_note == ""


def test_correction_note_works_without_vix_number():
    alerts, _ = annotate(Regime.CORRECTION, [T1], None, vix_avg=None)
    assert "volatile." in alerts[0].context_note


def test_bear_warns_on_every_non_capitulation_buy():
    alerts, confluence = annotate(Regime.BEAR, [T1, T2, T3], signal(3), rsi=31.2, dist_200d=-8.4)
    for a in alerts:
        assert "may keep falling" in a.context_note
        assert "RSI <= 25" in a.context_note and "<= -12%" in a.context_note
    assert "may keep falling" in confluence.context_note


def test_bear_tags_capitulation_with_the_real_numbers():
    alerts, confluence = annotate(Regime.BEAR, [T1, T3, CROSS_UP], signal(3), rsi=22.0, dist_200d=-13.5)
    assert alerts[0].context_note.startswith("CAPITULATION: RSI 22.0 and 200D SMA discount -13.5%")
    assert alerts[1].context_note.startswith("CAPITULATION")
    assert alerts[2].context_note == ""  # not a BUY TIER alert
    assert confluence.context_note.startswith("CAPITULATION")


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


def test_bear_missing_indicators_give_the_warning_not_a_crash():
    alerts, _ = annotate(Regime.BEAR, [T3], None, rsi=None, dist_200d=None)
    assert "may keep falling" in alerts[0].context_note


def test_bear_capitulation_thresholds_are_configurable():
    cfg = replace(CFG, capitulation_rsi=30.0, capitulation_sma_discount_pct=-8.0)
    alerts, _ = annotate(Regime.BEAR, [T3], None, rsi=29.0, dist_200d=-9.0, cfg=cfg)
    assert alerts[0].context_note.startswith("CAPITULATION")
    warn, _ = annotate(Regime.BEAR, [T3], None, rsi=31.0, dist_200d=-9.0, cfg=cfg)
    assert "RSI <= 30" in warn[0].context_note and "<= -8%" in warn[0].context_note


# --- sizes -------------------------------------------------------------------------------


@pytest.mark.parametrize("tier,expected", [(1, 1.0), (2, 1.5), (3, 2.0)])
def test_tier_sizes(tier, expected):
    assert annotate(Regime.NEUTRAL, [], signal(tier))[1].multiplier == expected


def test_uptrend_upgrades_only_tier_1():
    assert annotate(Regime.UPTREND, [], signal(1))[1].multiplier == 1.5
    assert annotate(Regime.UPTREND, [], signal(2))[1].multiplier == 1.5  # plain Tier-2 value
    assert annotate(Regime.UPTREND, [], signal(3))[1].multiplier == 2.0
    assert "UPTREND sizing" in annotate(Regime.UPTREND, [], signal(1))[1].context_note


def test_correction_and_bear_show_the_normal_size_next_to_the_warning():
    assert annotate(Regime.CORRECTION, [], signal(1))[1].multiplier == 1.0
    assert annotate(Regime.BEAR, [], signal(2), rsi=40.0)[1].multiplier == 1.5


def test_cheap_valuation_scales_up_and_stretched_scales_down():
    cheap = annotate(Regime.NEUTRAL, [], signal(2), valuation=CHEAP)[1]
    assert cheap.multiplier == pytest.approx(1.5 * 1.25) and "P/E 17.0 < 18" in cheap.context_note
    stretched = annotate(Regime.NEUTRAL, [], signal(2), valuation=STRETCHED)[1]
    assert stretched.multiplier == pytest.approx(1.5 * 0.5) and "P/E 25.0 > 24" in stretched.context_note


def test_regime_note_and_sizing_are_combined_in_one_note():
    note = annotate(Regime.UPTREND, [], signal(1), valuation=CHEAP)[1].context_note
    assert note.startswith("Market is in an uptrend") and "Sizing: UPTREND sizing for Tier-1" in note and "P/E 17.0" in note


def test_uptrend_and_cheap_stack():
    assert annotate(Regime.UPTREND, [], signal(1), valuation=CHEAP)[1].multiplier == pytest.approx(1.5 * 1.25)


def test_unknown_valuation_changes_nothing():
    out = annotate(Regime.NEUTRAL, [], signal(2), valuation=Valuation(None, "unknown"))[1]
    assert out.multiplier == 1.5 and out.context_note == ""


def test_custom_multipliers_are_honoured():
    cfg = replace(CFG, multiplier_tier2=2.5, multiplier_cheap_factor=2.0)
    assert annotate(Regime.NEUTRAL, [], signal(2), valuation=CHEAP, cfg=cfg)[1].multiplier == 5.0


def test_buy_tier_parsing():
    assert [rf.buy_tier(a) for a in (T1, T2, T3, CROSS_UP, TRIM, CROSS_DOWN)] == [1, 2, 3, None, None, None]


# --- trimming -------------------------------------------------------------------------


def trim(valuation, rsi, dist):
    return rf.check_trimming_for_context(
        ctx(Regime.BEAR, valuation), CFG, scheme_code="100", fund_name="Fund A", rsi=rsi, dist_52w=dist, rules=RULES,
    )


@pytest.mark.parametrize("valuation", [FAIR, CHEAP, Valuation(None, "unknown")])
def test_trimming_is_unchanged_unless_valuation_is_stretched(valuation):
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
