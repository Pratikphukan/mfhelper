"""End-to-end wiring of main.run with every external system faked.

Nothing here touches Google Sheets, AMFI, mfapi.in, Yahoo, NSE, SMTP or the data/ state
files; ``--dev`` is passed anyway, matching the project's safe-testing rule.
"""

from datetime import date
from types import SimpleNamespace

import pytest

import main as main_module
from mfhelper.config import (
    AlertEmailConfig, AlertRulesConfig, AlertSettings, FundConfig, GoogleSheetConfig, RegimeSettings, Settings,
)
from mfhelper.market_regime import MarketContext, Regime, Valuation
from mfhelper.mfapi import NavHistoryPoint

RULES = AlertRulesConfig(
    rsi_mild_pullback=55.0, rsi_moderate_dip=45.0, rsi_deep_oversold=35.0, rsi_overbought=70.0,
    sma_trend_support_pct=2.0, sma_moderate_discount_pct=-2.0, sma_deep_capitulation_pct=-10.0,
    discount_mild_pct=-5.0, discount_moderate_pct=-10.0, discount_deep_pct=-20.0, enable_sma_crossing=True,
)
EMAIL = AlertEmailConfig(True, "smtp.example.com", 587, True, "a@example.com", "x", "b@example.com")

# code -> (category, rsi, dist_52w, dist_200d)
FUNDS = {
    "111": ("equity", 31.0, -12.0, -8.0),    # oversold, not capitulating
    "222": ("equity", 20.0, -25.0, -15.0),   # capitulating
    "333": ("debt", 20.0, -25.0, -15.0),     # excluded from technical alerts entirely
    "444": ("equity", 80.0, -0.5, 6.0),      # overbought, trim candidate
}


class FakeAppender:
    created: list["FakeAppender"] = []

    def __init__(self, *, spreadsheet_id, worksheet_name, credentials_path, token_path):
        self.worksheet_name = worksheet_name
        FakeAppender.created.append(self)

    def sync_columns(self, *_a):
        return 0

    def migrate_sma_50d_to_200d(self, *_a):
        return 0

    def append_run_row(self, *_a):
        pass

    def trim_to_window(self, *_a):
        return 0


class FakeRegimeWriter:
    created: list["FakeRegimeWriter"] = []
    fail = False

    def __init__(self, *, spreadsheet_id, worksheet_name, credentials_path, token_path):
        self.spreadsheet_id = spreadsheet_id
        self.worksheet_name = worksheet_name
        self.recorded: list[tuple[str, MarketContext]] = []
        FakeRegimeWriter.created.append(self)

    def record(self, run_timestamp, context):
        if FakeRegimeWriter.fail:
            raise RuntimeError("sheet is down")
        self.recorded.append((run_timestamp, context))
        return 2


class FakeColumnStore:
    def __init__(self, *_a):
        pass

    def load(self):
        return []

    def save(self, *_a):
        pass


class FakeNavStore(FakeColumnStore):
    def load(self):
        return {}


@pytest.fixture
def harness(monkeypatch):
    FakeAppender.created = []
    FakeRegimeWriter.created = []
    FakeRegimeWriter.fail = False
    calls = {"dispatch": [], "build_context": 0}

    def settings_for(regime: RegimeSettings) -> AlertSettings:
        return AlertSettings(rules=RULES, email=EMAIL, regime=regime)

    state = {"alert_settings": settings_for(RegimeSettings()), "context": None}

    funds = dict(FUNDS)
    monkeypatch.setattr(
        main_module, "load_funds",
        lambda _p: [FundConfig(code=c, name=f"Fund {c}", category=v[0]) for c, v in funds.items()],
    )
    monkeypatch.setattr(
        main_module, "load_settings",
        lambda _p: Settings(GoogleSheetConfig("sheet-id", "Sheet1"), 30, "Asia/Kolkata"),
    )
    monkeypatch.setattr(main_module, "load_alert_settings", lambda _p: state["alert_settings"])
    monkeypatch.setattr(main_module, "fetch_and_parse", lambda: {})
    monkeypatch.setattr(main_module, "SheetColumnStore", FakeColumnStore)
    monkeypatch.setattr(main_module, "LastNavStore", FakeNavStore)
    monkeypatch.setattr(main_module, "SheetAppender", FakeAppender)
    monkeypatch.setattr(main_module, "RegimeSheetWriter", FakeRegimeWriter)

    current = {"code": None}

    def fake_history(code):
        current["code"] = code  # the metric fakes below read the fund being processed
        point = NavHistoryPoint(date(2026, 11, 5), 100.0)
        return SimpleNamespace(scheme_name=f"Fund {code}", history=[point], latest=point)

    monkeypatch.setattr(main_module, "mfapi_fetch_history", fake_history)
    monkeypatch.setattr(main_module, "compute_rsi", lambda *_a: funds[current["code"]][1])
    monkeypatch.setattr(main_module, "distance_from_52w_high", lambda *_a: funds[current["code"]][2])
    monkeypatch.setattr(main_module, "distance_from_200d_sma", lambda *_a: funds[current["code"]][3])

    def fake_dispatch(alerts, email_config, confluence=None, **kwargs):
        calls["dispatch"].append({"alerts": alerts, "confluence": confluence or [], **kwargs})
        return True

    monkeypatch.setattr(main_module, "dispatch_alerts_email", fake_dispatch)

    def fake_build(cfg, *, cache_dir):
        calls["build_context"] += 1
        return state["context"]

    monkeypatch.setattr(main_module, "build_market_context", fake_build)

    def run():
        return main_module.run(SimpleNamespace(dev=True))

    return SimpleNamespace(calls=calls, state=state, run=run, settings_for=settings_for, funds=funds)


def ctx(regime: Regime, valuation: Valuation = Valuation(22.0, "fair", source="nse")) -> MarketContext:
    return MarketContext(available=True, regime=regime, valuation=valuation, vix_avg=20.0)


def alert_types(call, code):
    return [a.alert_type for a in call["alerts"] if a.scheme_code == code]


def test_runs_only_against_the_dev_worksheet(harness):
    assert harness.run() == 0
    assert [a.worksheet_name for a in FakeAppender.created] == ["Sheet1 (Dev)"]


def test_disabled_feature_never_builds_context_and_passes_no_regime_arguments(harness):
    assert harness.run() == 0
    assert harness.calls["build_context"] == 0
    (call,) = harness.calls["dispatch"]
    assert "market_context" not in call and "suppressed" not in call
    assert all(sig.multiplier is None and sig.context_note == "" for sig in call["confluence"])
    assert {s.scheme_code for s in call["confluence"]} == {"111", "222"}
    assert [s.scheme_code for s in call["trimming_signals"]] == ["444"]
    assert not any(a.scheme_code == "333" for a in call["alerts"])


def fingerprint(call):
    """Everything the email would list, ignoring regime notes and sizes."""
    return (
        sorted((a.scheme_code, a.alert_type) for a in call["alerts"]),
        sorted((s.scheme_code, s.tier) for s in call["confluence"]),
        sorted((s.scheme_code, s.tier) for s in call["trimming_signals"]),
    )


@pytest.mark.parametrize("regime", list(Regime))
def test_regime_never_changes_which_alerts_are_sent(harness, regime):
    harness.run()
    (off,) = harness.calls["dispatch"]
    harness.calls["dispatch"].clear()

    harness.state["alert_settings"] = harness.settings_for(RegimeSettings(enable=True))
    harness.state["context"] = ctx(regime)
    assert harness.run() == 0
    (on,) = harness.calls["dispatch"]

    assert fingerprint(on) == fingerprint(off)
    assert on["market_context"].regime is regime
    assert "suppressed" not in on


def test_bear_market_labels_buys_instead_of_hiding_them(harness):
    harness.state["alert_settings"] = harness.settings_for(RegimeSettings(enable=True))
    harness.state["context"] = ctx(Regime.BEAR)
    assert harness.run() == 0
    (call,) = harness.calls["dispatch"]

    by_fund = {}
    for a in call["alerts"]:
        by_fund.setdefault(a.scheme_code, []).append(a)
    assert by_fund["111"], "fund 111 buys are still sent in a bear market"
    assert all("may keep falling" in a.context_note for a in by_fund["111"] if "BUY TIER" in a.alert_type)
    assert all(a.context_note.startswith("CAPITULATION") for a in by_fund["222"] if "BUY TIER" in a.alert_type)
    signals = {s.scheme_code: s for s in call["confluence"]}
    assert "may keep falling" in signals["111"].context_note
    assert signals["222"].context_note.startswith("CAPITULATION") and signals["222"].multiplier == 2.0
    assert "444" not in signals and [s.scheme_code for s in call["trimming_signals"]] == ["444"]


def test_uptrend_adds_notes_and_sizes(harness):
    harness.state["alert_settings"] = harness.settings_for(RegimeSettings(enable=True))
    harness.state["context"] = ctx(Regime.UPTREND)
    assert harness.run() == 0
    (call,) = harness.calls["dispatch"]
    assert all(s.multiplier is not None and "uptrend" in s.context_note for s in call["confluence"])


def test_stretched_valuation_tightens_trims_in_the_daily_run(harness):
    harness.funds["555"] = ("equity", 62.0, -6.5, 3.0)  # too mild for a standard trim

    harness.state["alert_settings"] = harness.settings_for(RegimeSettings(enable=True))
    harness.state["context"] = ctx(Regime.NEUTRAL, Valuation(25.0, "stretched", source="nse"))
    assert harness.run() == 0
    (call,) = harness.calls["dispatch"]
    assert sorted(s.scheme_code for s in call["trimming_signals"]) == ["444", "555"]

    harness.calls["dispatch"].clear()
    harness.state["context"] = ctx(Regime.NEUTRAL, Valuation(22.0, "fair", source="nse"))
    assert harness.run() == 0
    (call,) = harness.calls["dispatch"]
    assert [s.scheme_code for s in call["trimming_signals"]] == ["444"]


def test_unavailable_market_data_adds_no_notes(harness):
    harness.state["alert_settings"] = harness.settings_for(RegimeSettings(enable=True))
    harness.state["context"] = MarketContext(False, Regime.NEUTRAL, Valuation(None, "unknown"), notes=("no data",))
    assert harness.run() == 0
    (call,) = harness.calls["dispatch"]
    assert call["market_context"].available is False
    assert all(a.context_note == "" for a in call["alerts"])
    assert {s.scheme_code for s in call["confluence"]} == {"111", "222"}


# --- recording to the Market Regime tab ------------------------------------------------------


def test_feature_off_fetches_nothing_and_writes_no_regime_row(harness):
    assert harness.run() == 0
    assert harness.calls["build_context"] == 0 and FakeRegimeWriter.created == []


def test_record_only_writes_one_row_to_the_dev_tab_and_leaves_alerts_alone(harness):
    harness.run()
    (off,) = harness.calls["dispatch"]
    harness.calls["dispatch"].clear()

    harness.state["alert_settings"] = harness.settings_for(RegimeSettings(record_to_sheet=True))
    harness.state["context"] = ctx(Regime.BEAR)
    assert harness.run() == 0

    (writer,) = FakeRegimeWriter.created
    assert writer.worksheet_name == "Market Regime (Dev)" and writer.spreadsheet_id == "sheet-id"
    ((_, recorded),) = writer.recorded
    assert recorded.regime is Regime.BEAR

    (on,) = harness.calls["dispatch"]
    assert fingerprint(on) == fingerprint(off)
    assert "market_context" not in on  # no banner
    assert all(a.context_note == "" for a in on["alerts"])
    assert all(s.multiplier is None and s.context_note == "" for s in on["confluence"])
    assert FakeAppender.created[0].worksheet_name == "Sheet1 (Dev)"  # the NAV tab is untouched


def test_advice_only_does_not_write_to_the_sheet(harness):
    harness.state["alert_settings"] = harness.settings_for(RegimeSettings(enable=True))
    harness.state["context"] = ctx(Regime.UPTREND)
    assert harness.run() == 0
    assert FakeRegimeWriter.created == []
    (call,) = harness.calls["dispatch"]
    assert call["market_context"].regime is Regime.UPTREND


def test_both_switches_record_and_advise(harness):
    harness.state["alert_settings"] = harness.settings_for(RegimeSettings(enable=True, record_to_sheet=True))
    harness.state["context"] = ctx(Regime.UPTREND)
    assert harness.run() == 0
    assert harness.calls["build_context"] == 1  # fetched once, shared by both
    (writer,) = FakeRegimeWriter.created
    assert len(writer.recorded) == 1
    (call,) = harness.calls["dispatch"]
    assert call["market_context"].regime is Regime.UPTREND


def test_custom_tab_name_is_used(harness):
    harness.state["alert_settings"] = harness.settings_for(
        RegimeSettings(record_to_sheet=True, sheet_name="Market Mood")
    )
    harness.state["context"] = ctx(Regime.NEUTRAL)
    harness.run()
    assert FakeRegimeWriter.created[0].worksheet_name == "Market Mood (Dev)"


def test_unavailable_data_is_still_recorded(harness):
    harness.state["alert_settings"] = harness.settings_for(RegimeSettings(record_to_sheet=True))
    unavailable = MarketContext(False, Regime.NEUTRAL, Valuation(None, "unknown"), notes=("no data",))
    harness.state["context"] = unavailable
    assert harness.run() == 0
    ((_, recorded),) = FakeRegimeWriter.created[0].recorded
    assert recorded.available is False


def test_a_failing_regime_sheet_never_breaks_the_run_or_the_alerts(harness):
    FakeRegimeWriter.fail = True
    harness.state["alert_settings"] = harness.settings_for(RegimeSettings(record_to_sheet=True))
    harness.state["context"] = ctx(Regime.BEAR)
    assert harness.run() == 0
    assert len(harness.calls["dispatch"]) == 1  # alerts still went out
