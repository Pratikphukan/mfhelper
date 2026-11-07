from dataclasses import replace
from datetime import date, timedelta
import json
from pathlib import Path

import pytest

from mfhelper import market_regime as mr
from mfhelper.benchmarks import BenchmarkHistory, BenchmarkPoint
from mfhelper.config import RegimeSettings
from mfhelper.market_regime import MarketContext, Regime, SuppressedSignal, Valuation

TODAY = date(2026, 11, 6)  # a Friday
CFG = RegimeSettings(enable=True)
# One-day VIX "average" so tests can flip the regime on an exact session.
CFG_RAW_VIX = replace(CFG, vix_smoothing_days=1)


def session_dates(count: int, end: date = TODAY) -> list[date]:
    days: list[date] = []
    current = end
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current -= timedelta(days=1)
    return list(reversed(days))


def points(values: list[float], end: date = TODAY) -> list[BenchmarkPoint]:
    return [BenchmarkPoint(d, v) for d, v in zip(session_dates(len(values), end), values)]


def rising(count: int = 300, start: float = 100.0, step: float = 0.2) -> list[float]:
    return [start + step * i for i in range(count)]


def falling_after_flat() -> list[float]:
    return [100.0] * 250 + [100.0 - 0.6 * i for i in range(1, 51)]


def history(values: list[BenchmarkPoint], name: str = "X") -> BenchmarkHistory:
    from datetime import datetime, timezone

    return BenchmarkHistory(name, "PR", values, datetime.now(timezone.utc), "test")


def fetcher(index: list[BenchmarkPoint] | None, vix: list[BenchmarkPoint] | None):
    def fetch(ticker, **_kwargs):
        if ticker == CFG.index_ticker:
            return history(index) if index else None
        if ticker == CFG.vix_ticker:
            return history(vix) if vix else None
        raise AssertionError(ticker)

    return fetch


# --- classify_raw ---------------------------------------------------------------------


def test_bear_is_below_falling_200d_sma():
    closes = falling_after_flat()
    assert mr.classify_raw(closes, len(closes) - 1, 12.0, CFG) is Regime.BEAR


def test_bear_takes_precedence_over_vix_rules():
    closes = falling_after_flat()
    assert mr.classify_raw(closes, len(closes) - 1, 30.0, CFG) is Regime.BEAR
    assert mr.classify_raw(closes, len(closes) - 1, None, CFG) is Regime.BEAR


def test_below_200d_but_sma_still_rising_is_not_bear():
    closes = rising(300)
    closes[-1] = 100.0  # far below the 200D SMA (~150), but one low close barely moves the SMA
    sma_now = sum(closes[-200:]) / 200
    sma_before = sum(closes[-220:-20]) / 200
    assert sma_now > sma_before
    assert mr.classify_raw(closes, len(closes) - 1, 12.0, CFG) is not Regime.BEAR


@pytest.mark.parametrize("vix", [18.0, 25.0, 60.0])
def test_correction_has_no_upper_vix_cap(vix):
    closes = rising()
    assert mr.classify_raw(closes, len(closes) - 1, vix, CFG) is Regime.CORRECTION


def test_uptrend_needs_low_vix_and_index_above_50d():
    closes = rising()
    assert mr.classify_raw(closes, len(closes) - 1, 12.0, CFG) is Regime.UPTREND
    assert mr.classify_raw(closes, len(closes) - 1, 15.0, CFG) is Regime.NEUTRAL  # not strictly below 15
    flat = [100.0] * 300
    assert mr.classify_raw(flat, 299, 12.0, CFG) is Regime.NEUTRAL  # not above its 50D SMA


def test_vix_between_bands_is_neutral():
    closes = rising()
    for vix in (15.0, 16.5, 17.99):
        assert mr.classify_raw(closes, len(closes) - 1, vix, CFG) is Regime.NEUTRAL


def test_missing_vix_cannot_produce_vix_regimes():
    closes = rising()
    assert mr.classify_raw(closes, len(closes) - 1, None, CFG) is Regime.NEUTRAL


def test_too_little_history_is_unclassifiable():
    assert mr.classify_raw([100.0] * 215, 214, 12.0, CFG) is None
    assert mr.classify_raw([100.0] * 220, 219, 12.0, CFG) is Regime.NEUTRAL


# --- VIX smoothing --------------------------------------------------------------------


def test_vix_average_uses_only_sessions_up_to_the_day():
    vix = points([10, 11, 12, 13, 14, 15, 16])
    days = [p.date for p in vix]
    assert mr.vix_average_asof(vix, days[4], 5) == pytest.approx(12.0)
    assert mr.vix_average_asof(vix, days[6], 5) == pytest.approx(14.0)
    assert mr.vix_average_asof(vix, days[3], 5) is None


# --- confirmation replay --------------------------------------------------------------


def vix_series(index: list[BenchmarkPoint], tail: list[float], base: float = 12.0) -> list[BenchmarkPoint]:
    values = [base] * (len(index) - len(tail)) + tail
    return [BenchmarkPoint(p.date, v) for p, v in zip(index, values)]


def test_regime_change_needs_three_consecutive_sessions():
    index = points(rising())
    base = mr.replay_regime(index, vix_series(index, []), CFG_RAW_VIX)
    assert base.regime is Regime.UPTREND

    two_days = mr.replay_regime(index, vix_series(index, [20.0, 20.0]), CFG_RAW_VIX)
    assert two_days.regime is Regime.UPTREND
    assert two_days.raw_regime is Regime.CORRECTION
    assert (two_days.pending_regime, two_days.pending_days) == (Regime.CORRECTION, 2)

    three_days = mr.replay_regime(index, vix_series(index, [20.0, 20.0, 20.0]), CFG_RAW_VIX)
    assert three_days.regime is Regime.CORRECTION
    assert three_days.pending_regime is None


def test_flapping_signal_never_flips_the_regime():
    index = points(rising())
    tail = [20.0, 20.0, 12.0, 20.0, 20.0, 12.0, 20.0]
    result = mr.replay_regime(index, vix_series(index, tail), CFG_RAW_VIX)
    assert result.regime is Regime.UPTREND


def test_leaving_a_regime_is_also_confirmed():
    index = points(rising())
    vix = vix_series(index, [20.0] * 10 + [12.0, 12.0])
    result = mr.replay_regime(index, vix, CFG_RAW_VIX)
    assert result.regime is Regime.CORRECTION
    assert (result.pending_regime, result.pending_days) == (Regime.UPTREND, 2)


def test_replay_is_deterministic():
    index = points(rising())
    vix = vix_series(index, [20.0, 20.0, 20.0, 12.0])
    assert mr.replay_regime(index, vix, CFG_RAW_VIX) == mr.replay_regime(index, vix, CFG_RAW_VIX)


def test_replay_needs_enough_history():
    assert mr.replay_regime(points(rising(150)), [], CFG) is None


def test_regime_history_lists_raw_and_confirmed_per_session():
    index = points(rising())
    vix = vix_series(index, [20.0, 20.0])
    rows = mr.regime_history(index, vix, CFG_RAW_VIX, 3)
    assert [r.raw for r in rows] == [Regime.UPTREND, Regime.CORRECTION, Regime.CORRECTION]
    assert [r.effective for r in rows] == [Regime.UPTREND] * 3


# --- build_market_context -------------------------------------------------------------


def build(index, vix, tmp_path, **kwargs):
    return mr.build_market_context(
        kwargs.pop("cfg", CFG), cache_dir=tmp_path, today=TODAY,
        fetch_history=fetcher(index, vix), fetch_pe=kwargs.pop("fetch_pe", lambda: 22.0), **kwargs,
    )


def test_context_for_an_uptrend(tmp_path):
    index = points(rising())
    ctx = build(index, vix_series(index, [], base=12.0), tmp_path)
    assert ctx.available and ctx.regime is Regime.UPTREND
    assert ctx.as_of == TODAY and ctx.vix_avg == pytest.approx(12.0)
    assert ctx.valuation.state == "fair"


def test_context_for_a_bear_market_without_vix(tmp_path):
    ctx = build(points(falling_after_flat()), None, tmp_path)
    assert ctx.available and ctx.regime is Regime.BEAR
    assert any("INDIAVIX" in n for n in ctx.notes)


def test_missing_index_data_is_neutral_and_unavailable(tmp_path):
    ctx = build(None, None, tmp_path)
    assert not ctx.available and ctx.regime is Regime.NEUTRAL
    assert "no ^CRSLDX data" in ctx.notes[0]


def test_stale_index_data_is_neutral_and_unavailable(tmp_path):
    old = points(rising(), end=TODAY - timedelta(days=10))
    ctx = build(old, None, tmp_path)
    assert not ctx.available and "days old" in ctx.notes[0]


def test_data_exactly_at_the_age_limit_is_still_used(tmp_path):
    index = points(rising(), end=date(2026, 10, 30))  # a Friday, exactly 7 days before TODAY
    assert index[-1].date == date(2026, 10, 30)
    assert build(index, vix_series(index, []), tmp_path, cfg=replace(CFG, max_data_age_days=7)).available
    assert not build(index, vix_series(index, []), tmp_path, cfg=replace(CFG, max_data_age_days=6)).available


def test_stale_vix_is_dropped_but_index_regime_still_computed(tmp_path):
    index = points(rising())
    old_vix = points([12.0] * 300, end=TODAY - timedelta(days=30))
    ctx = build(index, old_vix, tmp_path)
    assert ctx.available and ctx.regime is Regime.NEUTRAL and ctx.vix_avg is None
    assert any("days old" in n for n in ctx.notes)


def test_fetch_exceptions_never_escape(tmp_path):
    def boom(*_a, **_k):
        raise RuntimeError("network down")

    def boom_pe():
        raise RuntimeError("nse down")

    ctx = mr.build_market_context(CFG, cache_dir=tmp_path, today=TODAY, fetch_history=boom, fetch_pe=boom_pe)
    assert not ctx.available and ctx.regime is Regime.NEUTRAL
    assert ctx.valuation.state == "unknown"


def test_short_history_is_unavailable(tmp_path):
    ctx = build(points(rising(100)), None, tmp_path)
    assert not ctx.available and "need at least 220" in ctx.notes[0]


# --- valuation ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pe,state", [(24.01, "stretched"), (24.0, "fair"), (20.0, "fair"), (18.0, "fair"), (17.99, "cheap")]
)
def test_valuation_state_boundaries(pe, state, tmp_path):
    valuation = mr.resolve_valuation(CFG, cache_dir=tmp_path, today=TODAY, fetch_pe=lambda: pe)
    assert valuation.state == state


def test_live_value_is_cached_and_used_after_nse_fails(tmp_path):
    mr.resolve_valuation(CFG, cache_dir=tmp_path, today=TODAY, fetch_pe=lambda: 25.5)
    cached = json.loads((tmp_path / mr.PE_CACHE_FILENAME).read_text())
    assert cached["pe"] == 25.5 and cached["fetched_on"] == TODAY.isoformat()

    later = TODAY + timedelta(days=3)
    valuation = mr.resolve_valuation(CFG, cache_dir=tmp_path, today=later, fetch_pe=lambda: None)
    assert (valuation.pe, valuation.source, valuation.as_of) == (25.5, "nse_cache", TODAY)


def test_stale_cache_is_not_used(tmp_path):
    mr.resolve_valuation(CFG, cache_dir=tmp_path, today=TODAY, fetch_pe=lambda: 25.5)
    later = TODAY + timedelta(days=8)
    valuation = mr.resolve_valuation(CFG, cache_dir=tmp_path, today=later, fetch_pe=lambda: None)
    assert valuation.state == "unknown" and valuation.pe is None


def test_manual_value_is_the_last_resort(tmp_path):
    cfg = replace(CFG, pe_manual=26.0, pe_manual_as_of=TODAY - timedelta(days=2))
    valuation = mr.resolve_valuation(cfg, cache_dir=tmp_path, today=TODAY, fetch_pe=lambda: None)
    assert (valuation.pe, valuation.source, valuation.stale, valuation.state) == (26.0, "manual", False, "stretched")


def test_manual_value_flags_staleness(tmp_path):
    old = replace(CFG, pe_manual=19.0, pe_manual_as_of=TODAY - timedelta(days=8))
    undated = replace(CFG, pe_manual=19.0)
    assert mr.resolve_valuation(old, cache_dir=tmp_path, today=TODAY, fetch_pe=lambda: None).stale
    assert mr.resolve_valuation(undated, cache_dir=tmp_path, today=TODAY, fetch_pe=lambda: None).stale
    assert "STALE" in mr.valuation_text(mr.resolve_valuation(old, cache_dir=tmp_path, today=TODAY, fetch_pe=lambda: None))


def test_live_value_beats_manual_value(tmp_path):
    cfg = replace(CFG, pe_manual=30.0, pe_manual_as_of=TODAY)
    valuation = mr.resolve_valuation(cfg, cache_dir=tmp_path, today=TODAY, fetch_pe=lambda: 21.0)
    assert (valuation.pe, valuation.source) == (21.0, "nse")


@pytest.mark.parametrize("bad", [None, 0.0, -3.0, 4.9, 100.1, float("nan"), "n/a"])
def test_implausible_live_values_are_rejected(bad, tmp_path):
    valuation = mr.resolve_valuation(CFG, cache_dir=tmp_path, today=TODAY, fetch_pe=lambda: bad)
    assert valuation.pe is None


def test_corrupt_cache_is_ignored(tmp_path):
    (tmp_path / mr.PE_CACHE_FILENAME).write_text("{not json")
    valuation = mr.resolve_valuation(CFG, cache_dir=tmp_path, today=TODAY, fetch_pe=lambda: None)
    assert valuation.state == "unknown"


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _fake_session(payload, calls):
    class FakeSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout=None):
            calls.append(url)
            return _FakeResponse(payload)

    return FakeSession


def test_nse_parser_picks_the_nifty_50_row(monkeypatch):
    import requests

    calls: list[str] = []
    payload = {"data": [{"index": "NIFTY NEXT 50", "pe": "30.1"}, {"index": "NIFTY 50", "pe": "22.37"}]}
    monkeypatch.setattr(requests, "Session", _fake_session(payload, calls))
    assert mr.fetch_nifty50_pe_from_nse() == pytest.approx(22.37)
    assert calls == [mr.NSE_HOME_URL, mr.NSE_ALL_INDICES_URL]  # cookie warm-up first


def test_nse_parser_survives_schema_drift(monkeypatch):
    import requests

    monkeypatch.setattr(requests, "Session", _fake_session({"unexpected": []}, []))
    assert mr.fetch_nifty50_pe_from_nse() is None
    monkeypatch.setattr(requests, "Session", _fake_session({"data": [{"index": "NIFTY 50"}]}, []))
    assert mr.fetch_nifty50_pe_from_nse() is None


def test_nse_network_error_returns_none(monkeypatch):
    import requests

    class Broken:
        def __init__(self):
            self.headers = {}

        def get(self, *_a, **_k):
            raise requests.ConnectionError("blocked")

    monkeypatch.setattr(requests, "Session", Broken)
    assert mr.fetch_nifty50_pe_from_nse() is None


# --- rendering ------------------------------------------------------------------------


def context(regime=Regime.CORRECTION, **overrides) -> MarketContext:
    base = dict(
        available=True, regime=regime, valuation=Valuation(22.1, "fair", source="nse", as_of=TODAY),
        as_of=TODAY, index_close=21000.0, sma_short=20500.0, sma_long=20000.0, vix_avg=19.4,
    )
    base.update(overrides)
    return MarketContext(**base)


def test_banner_summarises_regime_vix_and_valuation():
    text = mr.banner_text(context())
    assert "CORRECTION" in text and "VIX avg 19.4" in text and "above 200D SMA" in text
    assert "P/E 22.1 (fair)" in text


def test_banner_shows_a_pending_regime():
    text = mr.banner_text(context(Regime.UPTREND, pending_regime=Regime.CORRECTION, pending_days=2))
    assert "CORRECTION forming, day 2 of 3" in text


def test_unavailable_banner_says_alerts_are_unfiltered():
    ctx = MarketContext(False, Regime.NEUTRAL, mr.UNKNOWN_VALUATION, notes=("no ^CRSLDX data",))
    text = mr.banner_text(ctx)
    assert "Market context unavailable" in text and "without regime filtering" in text


def test_html_rendering_escapes_fund_names():
    suppressed = [SuppressedSignal("1", "<script>x</script> Fund", "Tier-1 confluence buy", "CORRECTION: <b>")]
    html = mr.render_suppressed_html(suppressed)
    assert "<script>" not in html and "&lt;script&gt;" in html and "Suppressed by market regime (1)" in html


def test_empty_renderers_return_nothing():
    assert mr.render_suppressed_html([]) == "" and mr.render_suppressed_html(None) == ""
    assert mr.render_regime_banner_html(None) == ""
