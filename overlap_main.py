"""Build an on-demand, portfolio-weighted fund overlap report.

Run with ``.venv/bin/python overlap_main.py``. Add ``--dev`` to use the
development holdings and report tabs instead of the production tabs.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys
from zoneinfo import ZoneInfo
from datetime import datetime

from mfhelper.config import load_settings
from mfhelper.overlap import (
    calculate_overlap_percentage,
    fetch_fund_holdings,
    fetch_isin_from_amfi,
    fetch_tickertape_sitemap_urls,
    get_tickertape_mappings_path,
    load_cached_mappings,
    resolve_mfid_by_isin,
    save_cached_mappings,
)
from mfhelper.overlap_sheet import OverlapSheetWriter, OVERLAP_TAB_DEFAULT
from mfhelper.portfolio_overlap import (
    FundDataIssue,
    PortfolioOverlapInputError,
    StockExposure,
    calculate_stock_exposures,
    read_portfolio_sheet,
)

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"

SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
CREDENTIALS_PATH = CONFIG_DIR / "credentials.json"
TOKEN_PATH = DATA_DIR / "token.json"
STALE_AFTER_DAYS = 30


def _configure_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / "mfhelper_overlap.log"
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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mfhelper-overlap",
        description="Build a portfolio-weighted overlap report from Google Sheets.",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Read Current Holdings (Dev) and write Portfolio Overlap (Dev).",
    )
    return parser.parse_args(argv)


def _fetch_constituents(
    positions: dict,
    *,
    log: logging.Logger,
) -> tuple[dict[str, list], dict[str, str], list[FundDataIssue]]:
    """Fetch constituent lists where possible, retaining failures for the report."""
    candidates = {
        code: position
        for code, position in positions.items()
        if position.current_value > 0
    }
    holdings_by_code: dict[str, list] = {}
    labels = {code: position.name for code, position in candidates.items()}
    issues: list[FundDataIssue] = []
    if not candidates:
        return holdings_by_code, labels, issues

    codes = list(candidates)
    code_to_isin: dict[str, str] = {}
    code_to_name: dict[str, str] = {}
    try:
        code_to_isin, code_to_name = fetch_isin_from_amfi(codes)
    except Exception as exc:
        log.warning("Could not fetch AMFI scheme details: %s", exc)
        issues.extend(
            FundDataIssue(code, position.name, position.current_value, "AMFI lookup failed")
            for code, position in candidates.items()
        )
        return holdings_by_code, labels, issues

    cache_path = get_tickertape_mappings_path()
    cached_mappings = load_cached_mappings(cache_path)
    mapped_ids: dict[str, str] = {}
    needs_sitemap: list[tuple[str, str, str]] = []

    for code, position in candidates.items():
        isin = code_to_isin.get(code)
        if not isin:
            issues.append(FundDataIssue(code, position.name, position.current_value, "AMFI code not found"))
            continue
        cached_id = cached_mappings.get(isin)
        if cached_id:
            mapped_ids[code] = cached_id
        else:
            needs_sitemap.append((code, isin, code_to_name.get(code, position.name)))

    sitemap_urls = None
    if needs_sitemap:
        try:
            sitemap_urls = fetch_tickertape_sitemap_urls()
        except Exception as exc:
            log.warning("Could not fetch Tickertape's fund list: %s", exc)
            issues.extend(
                FundDataIssue(code, candidates[code].name, candidates[code].current_value,
                              "Tickertape fund lookup failed")
                for code, _, _ in needs_sitemap
            )

    if sitemap_urls is not None:
        for code, isin, name in needs_sitemap:
            try:
                mf_id = resolve_mfid_by_isin(isin, name, sitemap_urls)
            except Exception as exc:
                log.warning("Could not resolve %s in Tickertape: %s", name, exc)
                mf_id = None
            if mf_id:
                mapped_ids[code] = mf_id
                cached_mappings[isin] = mf_id
            else:
                position = candidates[code]
                issues.append(FundDataIssue(code, position.name, position.current_value,
                                            "No verified Tickertape match"))

    save_cached_mappings(cache_path, cached_mappings)

    for code, mf_id in mapped_ids.items():
        position = candidates[code]
        try:
            holdings = fetch_fund_holdings(mf_id)
            if not holdings:
                issues.append(FundDataIssue(code, position.name, position.current_value,
                                            "Tickertape returned no constituent holdings"))
                continue
            holdings_by_code[code] = holdings
        except Exception as exc:
            log.warning("Could not fetch constituents for %s (%s): %s", position.name, code, exc)
            issues.append(FundDataIssue(code, position.name, position.current_value,
                                        "Tickertape constituent fetch failed"))

    return holdings_by_code, labels, issues


def _pairwise_report(holdings_by_code: dict[str, list]):
    codes = sorted(holdings_by_code)
    matrix: dict[str, dict[str, float]] = {}
    detailed: dict[tuple[str, str], tuple[float, list[dict]]] = {}
    for code_a in codes:
        matrix[code_a] = {}
        for code_b in codes:
            if code_a == code_b:
                matrix[code_a][code_b] = 100.0
                continue
            overlap, details = calculate_overlap_percentage(
                holdings_by_code[code_a], holdings_by_code[code_b]
            )
            matrix[code_a][code_b] = overlap
            pair = tuple(sorted((code_a, code_b)))
            detailed.setdefault(pair, (overlap, details))
    sorted_pairs = sorted(detailed.items(), key=lambda item: (-item[1][0], item[0]))
    return codes, matrix, sorted_pairs


def _print_summary(snapshot, exposures: list[StockExposure], issues: list[FundDataIssue], age_days: int) -> None:
    print(f"Groww statement: {snapshot.statement_date.isoformat()} ({age_days} days old)")
    print(f"Reported portfolio value: ₹{snapshot.total_current_value:,.2f}")
    if age_days > STALE_AFTER_DAYS:
        print(f"WARNING: statement is stale (older than {STALE_AFTER_DAYS} days).")
    print("\nLargest estimated underlying equity exposures:")
    if not exposures:
        print("  No constituent exposure could be calculated.")
    for item in exposures[:15]:
        label = f" ({item.ticker})" if item.ticker else ""
        print(
            f"  {item.company_name}{label}: ₹{item.estimated_value:,.2f} "
            f"({item.portfolio_pct:.2f}% of reported portfolio; {item.fund_count} funds)"
        )
    if snapshot.unmapped_positions or issues:
        print("\nCoverage warnings:")
        for position in snapshot.unmapped_positions:
            print(f"  {position.name}: ₹{position.current_value:,.2f} — {position.reason}")
        for issue in issues:
            print(f"  {issue.name} ({issue.code}): ₹{issue.current_value:,.2f} — {issue.reason}")


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    log = logging.getLogger("mfhelper.overlap_main")
    log.info("=== MFHelper portfolio-weighted overlap calculation starting ===")
    args = _parse_args(argv)

    try:
        settings = load_settings(SETTINGS_PATH)
    except Exception as exc:
        log.error("Could not load Google Sheets settings: %s", exc)
        return 2
    spreadsheet_id = settings.google_sheet.spreadsheet_id
    if not spreadsheet_id:
        log.error("No Google Sheet Spreadsheet ID configured.")
        return 2

    holdings_tab = "Current Holdings (Dev)" if args.dev else "Current Holdings"
    report_tab = f"{OVERLAP_TAB_DEFAULT} (Dev)" if args.dev else OVERLAP_TAB_DEFAULT
    try:
        snapshot, _fund_code_map = read_portfolio_sheet(
            spreadsheet_id=spreadsheet_id,
            credentials_path=CREDENTIALS_PATH,
            token_path=TOKEN_PATH,
            holdings_tab=holdings_tab,
        )
    except Exception as exc:
        log.error("Could not load required portfolio sheet data: %s", exc)
        return 2

    holdings_by_code, fund_labels, issues = _fetch_constituents(
        snapshot.positions_by_code, log=log
    )
    active_codes, matrix, sorted_pairs = _pairwise_report(holdings_by_code)
    exposures = calculate_stock_exposures(
        snapshot.positions_by_code,
        holdings_by_code,
        snapshot.total_current_value,
    )
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    age_days = max(0, (today - snapshot.statement_date).days)
    _print_summary(snapshot, exposures, issues, age_days)

    if active_codes:
        print("\nPairwise fund overlap matrix:")
        print("Fund / AMFI code | " + " | ".join(f"{fund_labels[code]} [{code}]" for code in active_codes))
        for code_a in active_codes:
            values = " | ".join(
                "100.00%" if code_a == code_b else f"{matrix[code_a][code_b]:.2f}%"
                for code_b in active_codes
            )
            print(f"{fund_labels[code_a]} [{code_a}] | {values}")

        high_overlap_pairs = [item for item in sorted_pairs if item[1][0] >= 10.0]
        if high_overlap_pairs:
            print("\nDetailed pairwise overlap (pairs at or above 10%):")
            for (code_a, code_b), (overlap, details) in high_overlap_pairs:
                print(f"  {fund_labels[code_a]} vs {fund_labels[code_b]}: {overlap:.2f}%")
                for detail in details[:8]:
                    print(f"    {detail['company_name']}: {detail['intersection']:.2f}% overlap contribution")

    try:
        writer = OverlapSheetWriter(
            spreadsheet_id=spreadsheet_id,
            worksheet_name=report_tab,
            credentials_path=CREDENTIALS_PATH,
            token_path=TOKEN_PATH,
        )
        writer.write_overlap_report(
            active_codes,
            fund_labels,
            matrix,
            sorted_pairs,
            portfolio_snapshot=snapshot,
            portfolio_exposures=exposures,
            fund_data_issues=issues,
            statement_age_days=age_days,
            stale_after_days=STALE_AFTER_DAYS,
        )
    except Exception as exc:
        log.exception("Failed to write the overlap report:")
        print(f"Could not write the report: {exc}", file=sys.stderr)
        return 3

    log.info("Updated report tab %r with %d mapped fund(s), %d constituent dataset(s).",
             report_tab, len(snapshot.positions_by_code), len(active_codes))
    print(f"\nUpdated Google Sheet tab '{report_tab}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
