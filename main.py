"""MFHelper entry point.

For each fund listed in config/funds.yaml:

- Fetches the latest NAV from AMFI's daily file (with mfapi.in fallback for
  funds AMFI hasn't published yet)
- Pulls full NAV history from mfapi.in once per run; this powers the
  52-week-high, 200-day SMA, and RSI metrics
- Computes Day Change % vs the previous run's NAV
- Computes Dist from 52W High % using the history
- Computes Dist from 200D SMA % using the history (blank if <200 NAV-publish
  days available)
- Computes RSI (14-day, Wilder smoothing) from the history (blank if <15
  NAV-publish days available)

Then appends one wide-format row per run to the configured Google Sheet
(merged Fund Name -> NAV / Day Change % / Dist from 52W High % /
Dist from 200D SMA % / RSI (14) sub-columns) and trims the sheet to the
rolling 30-run-date window.

Run manually:       python main.py
Scheduled (launchd) fires the same command at 10:30 AM IST every day.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import logging
import sys

from mfhelper.amfi import fetch_and_parse
from mfhelper.columns import SheetColumnStore, reconcile
from mfhelper.config import load_funds, load_settings, load_alert_settings
from mfhelper.metrics import (
    distance_from_200d_sma,
    distance_from_52w_high,
    rsi as compute_rsi,
)
from mfhelper.mfapi import MfapiResult, fetch_history as mfapi_fetch_history
from mfhelper.sheets import NavValue, SheetAppender
from mfhelper.state import LastNavStore, PrevNav
from mfhelper.alerts import check_fund_alerts, dispatch_alerts_email, check_confluence_signal

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"

FUNDS_PATH = CONFIG_DIR / "funds.yaml"
SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
ALERTS_PATH = CONFIG_DIR / "alerts.yaml"
CREDENTIALS_PATH = CONFIG_DIR / "credentials.json"
TOKEN_PATH = DATA_DIR / "token.json"
LAST_NAV_PATH = DATA_DIR / "last_nav.json"
COLUMNS_PATH = DATA_DIR / "sheet_columns.json"


def _configure_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / "mfhelper.log"
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    for handler in list(root.handlers):
        root.removeHandler(handler)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(fmt)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)


def run() -> int:
    log = logging.getLogger("mfhelper.main")

    funds = load_funds(FUNDS_PATH)
    settings = load_settings(SETTINGS_PATH)
    alert_settings = load_alert_settings(ALERTS_PATH)
    log.info(
        "Loaded %d funds, target sheet %s/%s. Alerts enabled: %s",
        len(funds),
        settings.google_sheet.spreadsheet_id,
        settings.google_sheet.worksheet,
        alert_settings.email.enable,
    )

    tz = ZoneInfo(settings.timezone)
    run_timestamp = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

    nav_index = fetch_and_parse()
    log.info("AMFI file parsed: %d scheme records", len(nav_index))

    col_store = SheetColumnStore(COLUMNS_PATH)
    existing_cols = col_store.load()
    desired_codes = [f.code for f in funds]
    reconciliation = reconcile(existing_cols, desired_codes)
    ordered_codes = reconciliation.updated
    if reconciliation.added:
        log.info(
            "New fund column(s) to append to sheet: %s", ", ".join(reconciliation.added)
        )

    # Surface orphan codes loudly. By design ``data/sheet_columns.json`` is
    # append-only -- removing a fund from ``funds.yaml`` preserves its
    # historical column with the original header. But "silent preservation"
    # has previously surprised users (they assume the column is meant for a
    # newer fund and rename its header by hand, producing a duplicate). One
    # explicit log line per run prevents that confusion.
    desired_set = set(desired_codes)
    orphan_codes = [c for c in existing_cols if c not in desired_set]
    if orphan_codes:
        log.warning(
            "%d orphan code(s) in data/sheet_columns.json missing from funds.yaml: %s. "
            "Their columns will keep their existing data and header but receive no fresh "
            "values today. If this was intentional, ignore. If you want to permanently "
            "drop them: remove the code from data/sheet_columns.json AND delete the "
            "corresponding 5-column block in the sheet (in that order). Do NOT manually "
            "rename the sheet header -- the system tracks columns by code, not label.",
            len(orphan_codes),
            ", ".join(orphan_codes),
        )

    nav_store = LastNavStore(LAST_NAV_PATH)
    prev_state = nav_store.load()

    all_triggered_alerts = []
    all_confluence_signals = []
    values_by_code: dict[str, NavValue] = {}
    new_state: dict[str, PrevNav] = dict(prev_state)
    missing_codes: list[str] = []
    fallback_codes: list[str] = []
    history_failed: list[str] = []
    sma_unavailable: list[str] = []
    rsi_unavailable: list[str] = []
    fund_by_code = {f.code: f for f in funds}
    display_names: dict[str, str] = {}
    histories_by_code: dict[str, MfapiResult] = {}

    for fund in funds:
        amfi_record = nav_index.get(fund.code)
        mfapi_result = mfapi_fetch_history(fund.code)
        if mfapi_result is not None:
            histories_by_code[fund.code] = mfapi_result

        if amfi_record is not None:
            current_nav = amfi_record.nav
            current_date = amfi_record.nav_date
            source_scheme_name = amfi_record.scheme_name
        elif mfapi_result is not None:
            latest = mfapi_result.latest
            current_nav = latest.nav
            current_date = latest.nav_date
            source_scheme_name = mfapi_result.scheme_name
            fallback_codes.append(fund.code)
            log.info(
                "Using mfapi.in NAV for %s: %.4f as of %s",
                fund.code, current_nav, current_date.isoformat(),
            )
        else:
            missing_codes.append(fund.code)
            log.warning(
                "Scheme code %s not found in AMFI or mfapi.in -- skipping", fund.code
            )
            continue

        display_names[fund.code] = (fund.name or source_scheme_name or fund.code)

        prev = prev_state.get(fund.code)
        if prev is None or prev.nav == 0:
            day_change_pct: float | None = None
        else:
            day_change_pct = round((current_nav - prev.nav) / prev.nav * 100, 4)

        if mfapi_result is not None:
            dist_52w_pct = distance_from_52w_high(
                mfapi_result.history, current_nav, current_date
            )
            dist_200d_sma_pct = distance_from_200d_sma(
                mfapi_result.history, current_nav, current_date
            )
            if dist_200d_sma_pct is None:
                sma_unavailable.append(fund.code)
            rsi_value = compute_rsi(mfapi_result.history, current_nav, current_date)
            if rsi_value is None:
                rsi_unavailable.append(fund.code)
        else:
            dist_52w_pct = None
            dist_200d_sma_pct = None
            rsi_value = None
            history_failed.append(fund.code)

        values_by_code[fund.code] = NavValue(
            nav=current_nav,
            day_change_pct=day_change_pct,
            dist_52w_pct=dist_52w_pct,
            dist_200d_sma_pct=dist_200d_sma_pct,
            rsi=rsi_value,
        )
        new_state[fund.code] = PrevNav(nav=current_nav, nav_date=current_date)

        # Check technical indicator buy/sell triggers
        triggered = check_fund_alerts(
            scheme_code=fund.code,
            fund_name=display_names[fund.code],
            history=mfapi_result.history if mfapi_result else [],
            current_nav=current_nav,
            current_date=current_date,
            current_rsi=rsi_value,
            current_dist_52w=dist_52w_pct,
            current_dist_200d_sma=dist_200d_sma_pct,
            rules=alert_settings.rules,
        )
        if triggered:
            all_triggered_alerts.extend(triggered)
            log.info("  [ALERT] Triggered %d indicator alert(s) for %s", len(triggered), fund.code)

        # Check for confluence dip-buying opportunities
        confluence = check_confluence_signal(
            scheme_code=fund.code,
            fund_name=display_names[fund.code],
            current_rsi=rsi_value,
            current_dist_52w=dist_52w_pct,
            current_dist_200d_sma=dist_200d_sma_pct,
            rules=alert_settings.rules,
        )
        if confluence:
            all_confluence_signals.append(confluence)
            log.info("  [CONFLUENCE] Triggered Tier-%d buy signal for %s", confluence.tier, fund.code)

    for code in ordered_codes:
        if code not in display_names:
            existing_fund = fund_by_code.get(code)
            display_names[code] = (
                (existing_fund.name if existing_fund and existing_fund.name else None)
                or code
            )

    if not values_by_code:
        log.error(
            "No values to write (all configured funds missing). Aborting."
        )
        return 2

    appender = SheetAppender(
        spreadsheet_id=settings.google_sheet.spreadsheet_id,
        worksheet_name=settings.google_sheet.worksheet,
        credentials_path=CREDENTIALS_PATH,
        token_path=TOKEN_PATH,
    )

    added = appender.sync_columns(ordered_codes, display_names)
    if added:
        log.info("Added %d new fund column group(s) to the sheet", added)

    def _backfill_sma(code: str, run_date, nav_in_sheet: float):
        result = histories_by_code.get(code)
        if result is None:
            return None
        return distance_from_200d_sma(result.history, nav_in_sheet, run_date)

    sma_migrated = appender.migrate_sma_50d_to_200d(ordered_codes, _backfill_sma)
    if sma_migrated:
        log.info(
            "Renamed SMA column header to %r and backfilled historical cells "
            "with 200-day SMA distances",
            "Dist from 200D SMA %",
        )

    appender.append_run_row(run_timestamp, ordered_codes, values_by_code)
    log.info("Appended run row for %s", run_timestamp)

    trimmed = appender.trim_to_window(settings.history_days)
    if trimmed:
        log.info(
            "Trimmed %d old row(s) to keep rolling %d-day window",
            trimmed,
            settings.history_days,
        )

    col_store.save(ordered_codes)
    nav_store.save(new_state)
    log.info(
        "Saved state: %d column(s), %d last-NAV entries",
        len(ordered_codes),
        len(new_state),
    )

    # Dispatch indicator alerts email digest if any are triggered
    dispatch_alerts_email(all_triggered_alerts, alert_settings.email, all_confluence_signals)

    if fallback_codes:
        log.info(
            "Used mfapi.in fallback for %d scheme(s): %s",
            len(fallback_codes),
            ", ".join(fallback_codes),
        )
    if history_failed:
        log.warning(
            "mfapi.in history unavailable for %d scheme(s) "
            "(Dist 52W H%%, Dist 200D SMA %%, and RSI left blank): %s",
            len(history_failed),
            ", ".join(history_failed),
        )
    if sma_unavailable:
        log.info(
            "Dist 200D SMA %% left blank for %d scheme(s) with <200 NAV-publish days "
            "of history: %s",
            len(sma_unavailable),
            ", ".join(sma_unavailable),
        )
    if rsi_unavailable:
        log.info(
            "RSI left blank for %d scheme(s) with <15 NAV-publish days of history: %s",
            len(rsi_unavailable),
            ", ".join(rsi_unavailable),
        )

    if missing_codes:
        log.warning("Finished with warnings. Missing codes: %s", ", ".join(missing_codes))
        return 1
    log.info("Done.")
    return 0


def main() -> int:
    _configure_logging()
    log = logging.getLogger("mfhelper.main")
    log.info("=== MFHelper run start ===")
    try:
        return run()
    except Exception:
        log.exception("Unhandled error during MFHelper run")
        return 3
    finally:
        log.info("=== MFHelper run end ===")


if __name__ == "__main__":
    sys.exit(main())
