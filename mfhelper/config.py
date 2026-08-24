"""Load and validate the YAML configuration files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


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
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    entries = raw.get("funds") or []
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"No funds configured in {path}. Add entries under the 'funds:' key.")

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

        expense_raw = entry.get("expense_ratio")
        expense_ratio_pct: float | None = None
        if expense_raw is not None:
            try:
                expense_ratio_pct = float(expense_raw)
            except (TypeError, ValueError):
                raise ValueError(
                    f"{path}: fund #{i} has non-numeric 'expense_ratio': {expense_raw!r}"
                )

        slug_raw = entry.get("groww_slug")
        groww_slug: str | None = None
        if slug_raw is not None:
            groww_slug = str(slug_raw).strip() or None

        category_raw = entry.get("category")
        category: str | None = None
        if category_raw is not None:
            category = str(category_raw).strip().lower() or None

        funds.append(FundConfig(
            code=code,
            name=name,
            expense_ratio_pct=expense_ratio_pct,
            groww_slug=groww_slug,
            category=category,
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
    return load_funds(path)


def load_settings(path: Path) -> Settings:
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
class AlertSettings:
    rules: AlertRulesConfig
    email: AlertEmailConfig


def load_alert_settings(path: Path) -> AlertSettings:
    """Load the alert configuration settings (``config/alerts.yaml``).

    Falls back to ``config/alerts_example.yaml`` if the ignored user config
    is missing.
    """
    target_path = path
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

    return AlertSettings(rules=rules, email=email)
