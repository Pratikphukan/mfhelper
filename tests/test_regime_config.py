from datetime import date
from pathlib import Path

import pytest
import yaml

from mfhelper.config import AlertSettings, RegimeSettings, load_alert_settings

EXAMPLE = Path(__file__).resolve().parent.parent / "config" / "alerts_example.yaml"


def load(tmp_path, body: str) -> AlertSettings:
    path = tmp_path / "alerts.yaml"
    path.write_text(body, encoding="utf-8")
    return load_alert_settings(path)


def test_regime_is_off_by_default(tmp_path):
    settings = load(tmp_path, "rules: {}\nemail: {enable: false}\n")
    assert settings.regime == RegimeSettings()
    assert settings.regime.enable is False


def test_alert_settings_can_still_be_built_without_a_regime():
    settings = AlertSettings(rules=None, email=None)  # type: ignore[arg-type]
    assert settings.regime.enable is False


def test_the_shipped_example_parses_to_the_defaults_and_stays_disabled():
    settings = load_alert_settings(EXAMPLE)
    assert settings.regime == RegimeSettings()


def test_full_section_is_parsed(tmp_path):
    body = """
regime:
  enable: true
  classification: {vix_low: 14, vix_high: 20, vix_smoothing_days: 3,
                   short_sma_days: 40, long_sma_days: 150, slope_lookback_days: 10, max_data_age_days: 4,
                   index_ticker: "^NSEI"}
  capitulation: {rsi: 22, sma_discount_pct: -15}
  valuation: {pe_stretched: 26, pe_cheap: 17, nifty50_pe: 23.5, nifty50_pe_as_of: "2026-11-01", stale_days: 5}
  multipliers: {tier1: 1.2, tier2: 1.8, tier3: 2.5, uptrend_tier1: 2.0, cheap_factor: 1.5, stretched_factor: 0.25}
  trimming: {rsi_offset: 4, dist_52w_offset_pts: 1.5}
"""
    regime = load(tmp_path, body).regime
    assert regime.enable is True
    assert (regime.vix_low, regime.vix_high, regime.vix_smoothing_days) == (14, 20, 3)
    assert (regime.short_sma_days, regime.long_sma_days, regime.slope_lookback_days) == (40, 150, 10)
    assert regime.max_data_age_days == 4 and regime.index_ticker == "^NSEI"
    assert (regime.capitulation_rsi, regime.capitulation_sma_discount_pct) == (22, -15)
    assert (regime.pe_stretched, regime.pe_cheap, regime.pe_manual) == (26, 17, 23.5)
    assert regime.pe_manual_as_of == date(2026, 11, 1) and regime.pe_stale_days == 5
    assert (regime.multiplier_tier1, regime.multiplier_tier2, regime.multiplier_tier3) == (1.2, 1.8, 2.5)
    assert (regime.multiplier_uptrend_tier1, regime.multiplier_cheap_factor) == (2.0, 1.5)
    assert regime.multiplier_stretched_factor == 0.25
    assert (regime.trim_rsi_offset, regime.trim_52w_offset_pts) == (4, 1.5)


def test_unquoted_yaml_dates_are_accepted(tmp_path):
    regime = load(tmp_path, "regime:\n  valuation: {nifty50_pe: 21, nifty50_pe_as_of: 2026-11-02}\n").regime
    assert regime.pe_manual_as_of == date(2026, 11, 2)


def test_partial_sections_keep_defaults(tmp_path):
    regime = load(tmp_path, "regime:\n  enable: true\n  multipliers: {tier3: 3}\n").regime
    assert regime.enable and regime.multiplier_tier3 == 3 and regime.multiplier_tier2 == 1.5


def test_null_section_is_fine(tmp_path):
    assert load(tmp_path, "regime:\n").regime == RegimeSettings()


@pytest.mark.parametrize(
    "body,message",
    [
        ("regime: [1, 2]", "'regime' must be a mapping"),
        ("regime: {enable: 'yes'}", "enable must be true or false"),
        ("regime: {enable: 1}", "enable must be true or false"),
        ("regime: {record_to_sheet: 'yes'}", "record_to_sheet must be true or false"),
        ("regime: {record_to_sheet: 1}", "record_to_sheet must be true or false"),
        ("regime: {sheet_name: ''}", "sheet_name must be a non-empty text"),
        ("regime: {sheet_name: 5}", "sheet_name must be a non-empty text"),
        ("regime: {sheet_name: '%s'}" % ("x" * 91), "at most 90 characters"),
        ("regime: {classification: {vix_low: 18, vix_high: 18}}", "vix_low (18.0) must be lower than vix_high"),
        ("regime: {classification: {vix_low: 20, vix_high: 15}}", "must be lower than vix_high"),
        ("regime: {classification: {vix_low: 0}}", "vix_low must be > 0"),
        ("regime: {classification: {vix_low: abc}}", "vix_low must be a number"),
        ("regime: {classification: {vix_low: .nan}}", "finite"),
        ("regime: {classification: {short_sma_days: 200}}", "short_sma_days (200) must be lower than long_sma_days"),
        ("regime: {classification: {slope_lookback_days: 0}}", "slope_lookback_days must be >= 1"),
        ("regime: {classification: {max_data_age_days: 2.5}}", "max_data_age_days must be a whole number"),
        ("regime: {classification: {vix_smoothing_days: true}}", "vix_smoothing_days must be a whole number"),
        ("regime: {classification: {index_ticker: ''}}", "must not be empty"),
        ("regime: {capitulation: {rsi: 0}}", "rsi must be > 0"),
        ("regime: {capitulation: {rsi: 120}}", "rsi must be <= 100"),
        ("regime: {capitulation: {sma_discount_pct: 5}}", "sma_discount_pct must be <= 0"),
        ("regime: {capitulation: {sma_discount_pct: 0}}", "must be negative"),
        ("regime: {valuation: {pe_cheap: 24, pe_stretched: 24}}", "pe_cheap (24.0) must be lower than pe_stretched"),
        ("regime: {valuation: {nifty50_pe: -1}}", "nifty50_pe must be > 0"),
        ("regime: {valuation: {nifty50_pe: 20, nifty50_pe_as_of: 'last tuesday'}}", "YYYY-MM-DD"),
        ("regime: {multipliers: {tier2: 0}}", "tier2 must be > 0"),
        ("regime: {multipliers: {stretched_factor: -0.5}}", "stretched_factor must be > 0"),
        ("regime: {trimming: {rsi_offset: -1}}", "rsi_offset must be >= 0"),
        ("regime: {trimming: {rsi_offset: 80}}", "rsi_offset must be <= 30"),
        ("regime: {trimming: [1]}", "'trimming' must be a mapping"),
    ],
)
def test_invalid_values_fail_loudly_with_the_offending_key(tmp_path, body, message):
    with pytest.raises(ValueError) as exc:
        load(tmp_path, body)
    assert message in str(exc.value)
    assert "alerts.yaml" in str(exc.value)


def test_example_file_documents_every_regime_key():
    raw = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))["regime"]
    documented = {
        "enable", "record_to_sheet", "sheet_name", "classification", "capitulation", "valuation",
        "multipliers", "trimming",
    }
    assert documented == set(raw)


def test_recording_and_advice_are_independent_switches(tmp_path):
    record_only = load(tmp_path, "regime: {record_to_sheet: true}").regime
    assert record_only.record_to_sheet is True and record_only.enable is False
    advice_only = load(tmp_path, "regime: {enable: true}").regime
    assert advice_only.enable is True and advice_only.record_to_sheet is False
    assert RegimeSettings().record_to_sheet is False and RegimeSettings().sheet_name == "Market Regime"


def test_sheet_name_is_configurable_and_trimmed(tmp_path):
    assert load(tmp_path, "regime: {sheet_name: '  Market Mood  '}").regime.sheet_name == "Market Mood"
