"""Load and validate the YAML configuration files."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import math
from pathlib import Path

import yaml


def resolve_config_path(path: Path) -> Path:
    """Prefer an ignored ``*.private.yaml`` override for local personal config."""
    private_path = path.with_name(f"{path.stem}.private{path.suffix}")
    if private_path.is_file():
        return private_path
    return path


@dataclass(frozen=True)
class FundConfig:
    code: str
    name: str | None
    # Optional manual override for expense ratio (analytics report only).
    # Used by mfhelper.analytics; ignored by the daily NAV scheduler.
    expense_ratio_pct: float | None = None
    # Optional Groww slug hint -- the URL fragment under
    # https://groww.in/mutual-funds/<slug>. Only needed for funds whose
    # AMFI name doesn't slug-derive to Groww's URL (typically funds whose
    # AMC has renamed them since launch -- Groww keeps the legacy slug).
    # Example: "jm-multi-strategy-fund-direct-growth".
    groww_slug: str | None = None
    # Optional asset category (e.g. "debt", "commodity", "equity").
    # Used to filter out false alerts on stable/non-equity asset classes.
    category: str | None = None
    # Optional investment weight percentage in your total portfolio.
    # Defaults to equal weighting if omitted.
    weight: float | None = None
    # Optional boolean flag to set active/inactive status.
    # Defaults to True. Inactive funds are ignored in daily tracking loops.
    active: bool = True


@dataclass(frozen=True)
class GoogleSheetConfig:
    spreadsheet_id: str
    worksheet: str


@dataclass(frozen=True)
class Settings:
    google_sheet: GoogleSheetConfig
    history_days: int
    timezone: str


def load_funds(path: Path) -> list[FundConfig]:
    path = resolve_config_path(path)
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    entries = raw.get("funds") or raw.get("etfs") or []
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"No funds configured in {path}. Add entries under 'funds:' or 'etfs:'.")

    funds: list[FundConfig] = []
    seen_codes: set[str] = set()
    for i, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: fund #{i} must be a mapping with at least a 'code' key.")
        code = entry.get("code")
        if code is None:
            raise ValueError(f"{path}: fund #{i} is missing 'code'.")
        code = str(code).strip()
        if not code:
            raise ValueError(f"{path}: fund #{i} has an empty 'code'.")
        if code in seen_codes:
            raise ValueError(f"{path}: duplicate scheme code {code!r}.")
        seen_codes.add(code)

        name = entry.get("name")
        if name is not None:
            name = str(name).strip() or None

        def parse_non_negative_number(field_name: str) -> float | None:
            raw_value = entry.get(field_name)
            if raw_value is None:
                return None
            # bool is a subclass of int in Python, but should not be accepted
            # as a numeric configuration value (True would otherwise become 1.0).
            if isinstance(raw_value, bool):
                raise ValueError(
                    f"{path}: fund #{i} field '{field_name}' must be a finite, "
                    f"non-negative number, got {raw_value!r}"
                )
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                raise ValueError(
                    f"{path}: fund #{i} field '{field_name}' must be a finite, "
                    f"non-negative number, got {raw_value!r}"
                ) from None
            if not math.isfinite(value) or value < 0:
                raise ValueError(
                    f"{path}: fund #{i} field '{field_name}' must be a finite, "
                    f"non-negative number, got {raw_value!r}"
                )
            return value

        expense_ratio_pct = parse_non_negative_number("expense_ratio")

        slug_raw = entry.get("groww_slug")
        groww_slug: str | None = None
        if slug_raw is not None:
            groww_slug = str(slug_raw).strip() or None

        category_raw = entry.get("category")
        category: str | None = None
        if category_raw is not None:
            category = str(category_raw).strip().lower() or None

        weight = parse_non_negative_number("weight")

        active: bool = True
        if "active" in entry:
            active_raw = entry["active"]
            if not isinstance(active_raw, bool):
                raise ValueError(
                    f"{path}: fund #{i} field 'active' must be a YAML boolean "
                    f"(true or false), got {active_raw!r}"
                )
            active = active_raw

        funds.append(FundConfig(
            code=code,
            name=name,
            expense_ratio_pct=expense_ratio_pct,
            groww_slug=groww_slug,
            category=category,
            weight=weight,
            active=active,
        ))
    return funds


def load_analytics_funds(path: Path) -> list[FundConfig]:
    """Load the analytics fund list (``config/analytics_funds.yaml``).

    Same schema as :func:`load_funds`: a top-level ``funds:`` list of
    ``{code, name?}`` entries. Kept as a separate file so the user can
    research a different (typically larger / aspirational) set of funds
    than the daily-tracking list in ``funds.yaml`` without disturbing
    the scheduler.
    """
    return load_funds(resolve_config_path(path))


def load_settings(path: Path) -> Settings:
    path = resolve_config_path(path)
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    gs_raw = raw.get("google_sheet") or {}
    spreadsheet_id = str(gs_raw.get("spreadsheet_id") or "").strip()
    worksheet = str(gs_raw.get("worksheet") or "Daily NAV").strip()
    if not spreadsheet_id or spreadsheet_id == "PASTE_SHEET_ID_HERE":
        raise ValueError(
            f"{path}: google_sheet.spreadsheet_id is not set. Paste the long ID from your sheet's URL."
        )

    history_days_raw = raw.get("history_days", 30)
    try:
        history_days = int(history_days_raw)
    except (TypeError, ValueError):
        raise ValueError(f"{path}: history_days must be an integer, got {history_days_raw!r}.")
    if history_days < 1:
        raise ValueError(f"{path}: history_days must be >= 1 (got {history_days}).")

    timezone = str(raw.get("timezone") or "Asia/Kolkata").strip()

    return Settings(
        google_sheet=GoogleSheetConfig(spreadsheet_id=spreadsheet_id, worksheet=worksheet),
        history_days=history_days,
        timezone=timezone,
    )


@dataclass(frozen=True)
class AlertRulesConfig:
    rsi_mild_pullback: float
    rsi_moderate_dip: float
    rsi_deep_oversold: float
    rsi_overbought: float
    sma_trend_support_pct: float
    sma_moderate_discount_pct: float
    sma_deep_capitulation_pct: float
    discount_mild_pct: float
    discount_moderate_pct: float
    discount_deep_pct: float
    enable_sma_crossing: bool


@dataclass(frozen=True)
class AlertEmailConfig:
    enable: bool
    smtp_server: str
    smtp_port: int
    use_tls: bool
    sender_email: str
    sender_password: str
    receiver_email: str


@dataclass(frozen=True)
class RegimeSettings:
    """Market regime / valuation context (``regime:`` in alerts.yaml). Off by default."""

    enable: bool = False

    # Regime classification (NIFTY 500 + India VIX).
    index_ticker: str = "^CRSLDX"
    vix_ticker: str = "^INDIAVIX"
    vix_low: float = 15.0            # smoothed VIX below this (and index > short SMA) = uptrend
    vix_high: float = 18.0           # smoothed VIX at/above this = correction
    vix_smoothing_days: int = 5      # VIX is averaged over this many sessions
    short_sma_days: int = 50
    long_sma_days: int = 200
    slope_lookback_days: int = 20    # 200D SMA is "falling" if below its value this many sessions ago
    max_data_age_days: int = 5       # older market data is treated as unavailable

    # Bear-regime capitulation (replaces Tier 3 while the regime is BEAR).
    capitulation_rsi: float = 25.0
    capitulation_sma_discount_pct: float = -12.0

    # Valuation (Nifty 50 P/E).
    pe_stretched: float = 24.0
    pe_cheap: float = 18.0
    pe_manual: float | None = None
    pe_manual_as_of: date | None = None
    pe_stale_days: int = 7

    # Suggested buy size, as a multiple of the user's normal SIP/top-up (text only).
    multiplier_tier1: float = 1.0
    multiplier_tier2: float = 1.5
    multiplier_tier3: float = 2.0
    multiplier_uptrend_tier1: float = 1.5
    multiplier_cheap_factor: float = 1.25
    multiplier_stretched_factor: float = 0.5

    # How much earlier trim alerts fire when valuations are stretched.
    trim_rsi_offset: float = 5.0
    trim_52w_offset_pts: float = 2.0


@dataclass(frozen=True)
class AlertSettings:
    rules: AlertRulesConfig
    email: AlertEmailConfig
    regime: RegimeSettings = field(default_factory=RegimeSettings)


def _section(raw: dict, key: str, where: str) -> dict:
    value = raw.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{where}: '{key}' must be a mapping.")
    return value


def _number(
    raw: dict, key: str, default: float, where: str, *, minimum: float | None = None,
    maximum: float | None = None, exclusive_minimum: bool = False,
) -> float:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where}.{key} must be a number (got {value!r}).")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{where}.{key} must be a finite number (got {value!r}).")
    if minimum is not None and (number <= minimum if exclusive_minimum else number < minimum):
        raise ValueError(f"{where}.{key} must be {'>' if exclusive_minimum else '>='} {minimum} (got {number}).")
    if maximum is not None and number > maximum:
        raise ValueError(f"{where}.{key} must be <= {maximum} (got {number}).")
    return number


def _whole(raw: dict, key: str, default: int, where: str, *, minimum: int = 1) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{where}.{key} must be a whole number (got {value!r}).")
    if value < minimum:
        raise ValueError(f"{where}.{key} must be >= {minimum} (got {value}).")
    return value


def _parse_regime(raw: dict, source: str) -> RegimeSettings:
    if raw is None:
        return RegimeSettings()
    if not isinstance(raw, dict):
        raise ValueError(f"{source}: 'regime' must be a mapping.")
    where = f"{source}: regime"
    defaults = RegimeSettings()

    enable = raw.get("enable", defaults.enable)
    if not isinstance(enable, bool):
        raise ValueError(f"{where}.enable must be true or false (got {enable!r}).")

    classification = _section(raw, "classification", where)
    capitulation = _section(raw, "capitulation", where)
    valuation = _section(raw, "valuation", where)
    multipliers = _section(raw, "multipliers", where)
    trimming = _section(raw, "trimming", where)

    cw = f"{where}.classification"
    vix_low = _number(classification, "vix_low", defaults.vix_low, cw, minimum=0, exclusive_minimum=True)
    vix_high = _number(classification, "vix_high", defaults.vix_high, cw, minimum=0, exclusive_minimum=True)
    if vix_low >= vix_high:
        raise ValueError(f"{cw}: vix_low ({vix_low}) must be lower than vix_high ({vix_high}).")
    short_sma = _whole(classification, "short_sma_days", defaults.short_sma_days, cw, minimum=2)
    long_sma = _whole(classification, "long_sma_days", defaults.long_sma_days, cw, minimum=2)
    if short_sma >= long_sma:
        raise ValueError(f"{cw}: short_sma_days ({short_sma}) must be lower than long_sma_days ({long_sma}).")
    index_ticker = str(classification.get("index_ticker", defaults.index_ticker)).strip()
    vix_ticker = str(classification.get("vix_ticker", defaults.vix_ticker)).strip()
    if not index_ticker or not vix_ticker:
        raise ValueError(f"{cw}: index_ticker and vix_ticker must not be empty.")

    kw = f"{where}.capitulation"
    capitulation_rsi = _number(
        capitulation, "rsi", defaults.capitulation_rsi, kw, minimum=0, maximum=100, exclusive_minimum=True
    )
    capitulation_discount = _number(
        capitulation, "sma_discount_pct", defaults.capitulation_sma_discount_pct, kw, maximum=0
    )
    if capitulation_discount == 0:
        raise ValueError(f"{kw}.sma_discount_pct must be negative (got 0).")

    vw = f"{where}.valuation"
    pe_stretched = _number(valuation, "pe_stretched", defaults.pe_stretched, vw, minimum=0, exclusive_minimum=True)
    pe_cheap = _number(valuation, "pe_cheap", defaults.pe_cheap, vw, minimum=0, exclusive_minimum=True)
    if pe_cheap >= pe_stretched:
        raise ValueError(f"{vw}: pe_cheap ({pe_cheap}) must be lower than pe_stretched ({pe_stretched}).")
    pe_manual = None
    if valuation.get("nifty50_pe") is not None:
        pe_manual = _number(valuation, "nifty50_pe", 0.0, vw, minimum=0, exclusive_minimum=True)
    as_of_raw = valuation.get("nifty50_pe_as_of")
    pe_as_of: date | None = None
    if as_of_raw is not None:
        if isinstance(as_of_raw, datetime):
            pe_as_of = as_of_raw.date()
        elif isinstance(as_of_raw, date):
            pe_as_of = as_of_raw
        else:
            try:
                pe_as_of = date.fromisoformat(str(as_of_raw).strip())
            except ValueError as exc:
                raise ValueError(f"{vw}.nifty50_pe_as_of must be a YYYY-MM-DD date (got {as_of_raw!r}).") from exc

    mw = f"{where}.multipliers"
    tw = f"{where}.trimming"
    positive = {"minimum": 0, "exclusive_minimum": True}
    return RegimeSettings(
        enable=enable,
        index_ticker=index_ticker,
        vix_ticker=vix_ticker,
        vix_low=vix_low,
        vix_high=vix_high,
        vix_smoothing_days=_whole(classification, "vix_smoothing_days", defaults.vix_smoothing_days, cw),
        short_sma_days=short_sma,
        long_sma_days=long_sma,
        slope_lookback_days=_whole(classification, "slope_lookback_days", defaults.slope_lookback_days, cw),
        max_data_age_days=_whole(classification, "max_data_age_days", defaults.max_data_age_days, cw),
        capitulation_rsi=capitulation_rsi,
        capitulation_sma_discount_pct=capitulation_discount,
        pe_stretched=pe_stretched,
        pe_cheap=pe_cheap,
        pe_manual=pe_manual,
        pe_manual_as_of=pe_as_of,
        pe_stale_days=_whole(valuation, "stale_days", defaults.pe_stale_days, vw),
        multiplier_tier1=_number(multipliers, "tier1", defaults.multiplier_tier1, mw, **positive),
        multiplier_tier2=_number(multipliers, "tier2", defaults.multiplier_tier2, mw, **positive),
        multiplier_tier3=_number(multipliers, "tier3", defaults.multiplier_tier3, mw, **positive),
        multiplier_uptrend_tier1=_number(
            multipliers, "uptrend_tier1", defaults.multiplier_uptrend_tier1, mw, **positive
        ),
        multiplier_cheap_factor=_number(
            multipliers, "cheap_factor", defaults.multiplier_cheap_factor, mw, **positive
        ),
        multiplier_stretched_factor=_number(
            multipliers, "stretched_factor", defaults.multiplier_stretched_factor, mw, **positive
        ),
        trim_rsi_offset=_number(trimming, "rsi_offset", defaults.trim_rsi_offset, tw, minimum=0, maximum=30),
        trim_52w_offset_pts=_number(
            trimming, "dist_52w_offset_pts", defaults.trim_52w_offset_pts, tw, minimum=0, maximum=20
        ),
    )


def load_alert_settings(path: Path) -> AlertSettings:
    """Load the alert configuration settings (``config/alerts.yaml``).

    Falls back to ``config/alerts_example.yaml`` if the ignored user config
    is missing.
    """
    target_path = resolve_config_path(path)
    if not target_path.exists():
        example_path = path.parent / "alerts_example.yaml"
        if example_path.exists():
            target_path = example_path
        else:
            raise FileNotFoundError(f"Alert configuration file not found at {path}")

    with target_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    rules_raw = raw.get("rules") or {}
    email_raw = raw.get("email") or {}

    rules = AlertRulesConfig(
        rsi_mild_pullback=float(rules_raw.get("rsi_mild_pullback", 55.0)),
        rsi_moderate_dip=float(rules_raw.get("rsi_moderate_dip", 45.0)),
        rsi_deep_oversold=float(rules_raw.get("rsi_deep_oversold", 35.0)),
        rsi_overbought=float(rules_raw.get("rsi_overbought", 70.0)),
        sma_trend_support_pct=float(rules_raw.get("sma_trend_support_pct", 2.0)),
        sma_moderate_discount_pct=float(rules_raw.get("sma_moderate_discount_pct", -2.0)),
        sma_deep_capitulation_pct=float(rules_raw.get("sma_deep_capitulation_pct", -10.0)),
        discount_mild_pct=float(rules_raw.get("discount_mild_pct", -5.0)),
        discount_moderate_pct=float(rules_raw.get("discount_moderate_pct", -10.0)),
        discount_deep_pct=float(rules_raw.get("discount_deep_pct", -20.0)),
        enable_sma_crossing=bool(rules_raw.get("enable_sma_crossing", True)),
    )

    email = AlertEmailConfig(
        enable=bool(email_raw.get("enable", False)),
        smtp_server=str(email_raw.get("smtp_server", "smtp.gmail.com")).strip(),
        smtp_port=int(email_raw.get("smtp_port", 587)),
        use_tls=bool(email_raw.get("use_tls", True)),
        sender_email=str(email_raw.get("sender_email", "")).strip(),
        sender_password=str(email_raw.get("sender_password", "")),
        receiver_email=str(email_raw.get("receiver_email", "")).strip(),
    )

    regime = _parse_regime(raw.get("regime"), str(target_path))

    return AlertSettings(rules=rules, email=email, regime=regime)
