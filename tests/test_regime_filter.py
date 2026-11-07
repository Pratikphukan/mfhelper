from dataclasses import replace
from datetime import date

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


def decide(regime, alerts=(), confluence=None, rsi=40.0, dist_200d=-5.0, valuation=FAIR, cfg=CFG):
    return rf.apply_regime_to_buys(
        ctx(regime, valuation), cfg, scheme_code="100", fund_name="Fund A", rsi=rsi,
        dist_200d_sma=dist_200d, alerts=list(alerts), confluence=confluence,
    )


T1 = alert("BUY TIER 1 / MILD PULLBACK")
T2 = alert("BUY TIER 2 / MODERATE DIP")
T3 = alert("BUY TIER 3 / DEEP OVERSOLD")
CROSS_UP = alert("BULLISH TREND CROSS-ABOVE", "200D SMA Trend Crossing")
CROSS_DOWN = alert("BEARISH TREND CROSS-BELOW", "200D SMA Trend Crossing")
TRIM = alert("MOMENTUM WARNING / TRIM")


# --- multipliers ----------------------------------------------------------------------


@pytest.mark.parametrize("tier,expected", [(1, 1.0), (2, 1.5), (3, 2.0)])
def test_neutral_uses_the_plain_tier_multipliers(tier, expected):
    out = decide(Regime.NEUTRAL, confluence=signal(tier)).confluence
    assert out.multiplier == expected and out.context_note == ""


def test_uptrend_upgrades_only_tier_1():
    assert decide(Regime.UPTREND, confluence=signal(1)).confluence.multiplier == 1.5
    assert decide(Regime.UPTREND, confluence=signal(2)).confluence.multiplier == 1.5  # plain Tier-2 value
    assert decide(Regime.UPTREND, confluence=signal(3)).confluence.multiplier == 2.0
    assert "UPTREND sizing" in decide(Regime.UPTREND, confluence=signal(1)).confluence.context_note


def test_cheap_valuation_scales_buys_up_and_stretched_scales_them_down():
    cheap = decide(Regime.NEUTRAL, confluence=signal(2), valuation=CHEAP).confluence
    assert cheap.multiplier == pytest.approx(1.5 * 1.25) and "P/E 17.0 < 18" in cheap.context_note
    stretched = decide(Regime.NEUTRAL, confluence=signal(2), valuation=STRETCHED).confluence
    assert stretched.multiplier == pytest.approx(1.5 * 0.5) and "P/E 25.0 > 24" in stretched.context_note


def test_uptrend_and_cheap_stack():
    out = decide(Regime.UPTREND, confluence=signal(1), valuation=CHEAP).confluence
    assert out.multiplier == pytest.approx(1.5 * 1.25)


def test_unknown_valuation_changes_nothing():
    out = decide(Regime.NEUTRAL, confluence=signal(2), valuation=Valuation(None, "unknown")).confluence
    assert out.multiplier == 1.5 and out.context_note == ""


def test_custom_multipliers_are_honoured():
    cfg = replace(CFG, multiplier_tier2=2.5, multiplier_cheap_factor=2.0)
    out = decide(Regime.NEUTRAL, confluence=signal(2), valuation=CHEAP, cfg=cfg).confluence
    assert out.multiplier == 5.0


# --- neutral / uptrend ----------------------------------------------------------------


@pytest.mark.parametrize("regime", [Regime.NEUTRAL, Regime.UPTREND])
def test_neutral_and_uptrend_suppress_nothing(regime):
    alerts = [T1, T2, T3, CROSS_UP, CROSS_DOWN, TRIM]
    out = decide(regime, alerts, signal(1))
    assert out.alerts == alerts and out.suppressed is None and out.confluence.tier == 1


def test_unavailable_context_behaves_like_neutral():
    out = rf.apply_regime_to_buys(
        ctx(Regime.NEUTRAL, available=False), CFG, scheme_code="100", fund_name="Fund A", rsi=20.0,
        dist_200d_sma=-30.0, alerts=[T1, T3], confluence=signal(3),
    )
    assert out.alerts == [T1, T3] and out.suppressed is None


# --- correction -----------------------------------------------------------------------


def test_correction_drops_tier_1_alerts_and_keeps_the_rest():
    out = decide(Regime.CORRECTION, [T1, T2, T3, CROSS_UP, CROSS_DOWN, TRIM], None)
    assert out.alerts == [T2, T3, CROSS_UP, CROSS_DOWN, TRIM]
    assert out.suppressed.label == "1 single-indicator buy alert"
    assert out.suppressed.reason == "CORRECTION: Tier-1 buys are suppressed"


def test_correction_suppresses_a_tier_1_confluence():
    out = decide(Regime.CORRECTION, [T1], signal(1))
    assert out.confluence is None and out.alerts == []
    assert out.suppressed.label == "Tier-1 confluence buy + 1 single-indicator buy alert"


@pytest.mark.parametrize("tier", [2, 3])
def test_correction_keeps_tier_2_and_3_confluence(tier):
    out = decide(Regime.CORRECTION, [], signal(tier))
    assert out.confluence.tier == tier and out.suppressed is None


def test_correction_with_nothing_to_suppress_reports_nothing():
    assert decide(Regime.CORRECTION, [T2], None).suppressed is None


# --- bear -----------------------------------------------------------------------------


def test_bear_suppresses_every_buy_when_not_capitulating():
    out = decide(Regime.BEAR, [T1, T2, T3, CROSS_UP, CROSS_DOWN, TRIM], signal(3), rsi=31.2, dist_200d=-8.4)
    assert out.alerts == [CROSS_DOWN, TRIM]  # sell-side alerts always pass
    assert out.confluence is None
    assert out.suppressed.label == "Tier-3 confluence buy + 4 single-indicator buy alerts"
    assert "RSI 31.2, -8.4%" in out.suppressed.reason and "RSI <= 25" in out.suppressed.reason


def test_bear_capitulation_keeps_only_tier_3_alerts_and_builds_a_signal():
    out = decide(Regime.BEAR, [T1, T2, T3, CROSS_UP, TRIM], signal(1), rsi=22.0, dist_200d=-13.5)
    assert out.alerts == [T3, TRIM]
    assert out.suppressed is None
    assert out.confluence.tier == 3 and out.confluence.multiplier == 2.0
    assert any("RSI is 22.00" in r for r in out.confluence.reasons)
    assert any("-13.50%" in r for r in out.confluence.reasons)
    assert out.confluence.groww_link.endswith("q=Fund+A")


def test_bear_capitulation_replaces_a_normal_tier_3_confluence():
    out = decide(Regime.BEAR, [], signal(3), rsi=20.0, dist_200d=-15.0)
    assert out.confluence.suggestion.startswith("Capitulation Buy")


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


def test_bear_missing_indicators_are_explained_as_n_a():
    out = decide(Regime.BEAR, [T3], None, rsi=None, dist_200d=None)
    assert "RSI n/a, n/a" in out.suppressed.reason


def test_bear_capitulation_thresholds_are_configurable():
    cfg = replace(CFG, capitulation_rsi=30.0, capitulation_sma_discount_pct=-8.0)
    assert decide(Regime.BEAR, [T3], None, rsi=29.0, dist_200d=-9.0, cfg=cfg).confluence.tier == 3


def test_bear_capitulation_with_cheap_valuation_sizes_up():
    out = decide(Regime.BEAR, [T3], None, rsi=20.0, dist_200d=-15.0, valuation=CHEAP).confluence
    assert out.multiplier == pytest.approx(2.0 * 1.25)


# --- tier parsing ---------------------------------------------------------------------


def test_buy_tier_parsing():
    assert [rf.buy_tier(a) for a in (T1, T2, T3, CROSS_UP, TRIM, CROSS_DOWN)] == [1, 2, 3, None, None, None]
    assert rf.is_bullish_cross(CROSS_UP) and not rf.is_bullish_cross(CROSS_DOWN)


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


def test_regime_never_suppresses_trims():
    for regime in Regime:
        out = rf.check_trimming_for_context(
            ctx(regime), CFG, scheme_code="100", fund_name="Fund A", rsi=80.0, dist_52w=-0.5, rules=RULES,
        )
        assert out is not None and out.tier == 3
