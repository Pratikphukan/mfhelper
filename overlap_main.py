"""Mutual Fund Portfolio Overlap report generator (one-shot CLI).

Calculates the percentage of overlapping stocks between every pair of
configured mutual funds to identify hidden diversification/concentration risk.

Run on demand:

    .venv/bin/python overlap_main.py

Exit codes:
  0  Success
  2  Configuration error
  3  Unhandled exception.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

from mfhelper.config import load_funds, load_settings
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

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"

FUNDS_PATH_DEFAULT = CONFIG_DIR / "funds.yaml"
SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
CREDENTIALS_PATH = CONFIG_DIR / "credentials.json"
TOKEN_PATH = DATA_DIR / "token.json"


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
    p = argparse.ArgumentParser(
        prog="mfhelper-overlap",
        description="Compute pairwise stock holdings overlap between mutual funds.",
    )
    p.add_argument(
        "--funds",
        type=str,
        default=str(FUNDS_PATH_DEFAULT),
        help="Path or name of the funds YAML file to check (default: config/funds.yaml).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    log = logging.getLogger("mfhelper.overlap_main")
    log.info("=== MFHelper Portfolio Overlap calculation starting ===")
    
    args = _parse_args(argv)
    funds_path = Path(args.funds)
    if not funds_path.exists():
        log.error("Funds file not found at: %s", funds_path)
        return 2

    # 1. Load funds
    try:
        funds = load_funds(funds_path)
    except Exception as e:
        log.error("Failed to load funds file: %s", e)
        return 2

    if not funds:
        log.error("No funds configured in: %s", funds_path)
        return 2

    # 2. Get ISINs from AMFI
    codes = [str(f.code) for f in funds]
    try:
        code_to_isin, code_to_name = fetch_isin_from_amfi(codes)
    except Exception as e:
        log.exception("Failed to fetch ISIN codes from AMFI:")
        return 3

    # 3. Load cache and resolve Tickertape mfId
    mappings_path = get_tickertape_mappings_path()
    cached_mappings = load_cached_mappings(mappings_path)
    
    mapped_ids = {}
    sitemap_urls = None  # Lazy loaded if needed
    
    for fund in funds:
        isin = code_to_isin.get(str(fund.code))
        if not isin:
            log.warning("AMFI code %s not found in AMFI master list -- skipping.", fund.code)
            continue
            
        mf_id = cached_mappings.get(isin)
        if mf_id:
            mapped_ids[fund.code] = mf_id
        else:
            if sitemap_urls is None:
                try:
                    sitemap_urls = fetch_tickertape_sitemap_urls()
                except Exception as e:
                    log.exception("Failed to download Tickertape sitemap:")
                    return 3
                    
            resolved_id = resolve_mfid_by_isin(isin, fund.name or code_to_name[str(fund.code)], sitemap_urls)
            if resolved_id:
                mapped_ids[fund.code] = resolved_id
                cached_mappings[isin] = resolved_id

    save_cached_mappings(mappings_path, cached_mappings)

    # 4. Fetch live holdings for each fund
    fund_holdings = {}
    fund_labels = {}
    
    for fund in funds:
        mf_id = mapped_ids.get(fund.code)
        if not mf_id:
            continue
        try:
            holdings = fetch_fund_holdings(mf_id)
            fund_holdings[fund.code] = holdings
            fund_labels[fund.code] = fund.name or code_to_name[str(fund.code)]
        except Exception as e:
            log.warning("Failed to fetch holdings for %s (Tickertape ID: %s): %s", fund.code, mf_id, e)

    active_codes = list(fund_holdings.keys())
    if len(active_codes) < 2:
        log.error("Need at least 2 resolved funds with holdings to calculate overlap. Found %d.", len(active_codes))
        return 2

    # 5. Compute pairwise overlap matrix
    matrix = {}
    detailed_overlaps = {}
    
    for i, code_a in enumerate(active_codes):
        matrix[code_a] = {}
        for code_b in active_codes:
            if code_a == code_b:
                matrix[code_a][code_b] = 100.0
                continue
                
            overlap, details = calculate_overlap_percentage(fund_holdings[code_a], fund_holdings[code_b])
            matrix[code_a][code_b] = overlap
            
            # Save detail for A -> B (or B -> A, keeping order sorted)
            pair_key = tuple(sorted([code_a, code_b]))
            if pair_key not in detailed_overlaps:
                detailed_overlaps[pair_key] = (overlap, details)

    # 6. Print Overlap Matrix Table
    print("\n" + "=" * 100)
    print("MUTUAL FUND PORTFOLIO OVERLAP MATRIX (%)")
    print("=" * 100)
    
    # Header row
    col_width = 18
    sys.stdout.write(f"{'Fund / Code':<20}")
    for code in active_codes:
        short_col_name = fund_labels[code][:15]
        sys.stdout.write(f"| {short_col_name:^{col_width}}")
    sys.stdout.write("\n" + "-" * (20 + (col_width + 2) * len(active_codes)) + "\n")
    
    # Rows
    for code_a in active_codes:
        label_truncated = fund_labels[code_a][:18]
        sys.stdout.write(f"{label_truncated:<20}")
        for code_b in active_codes:
            overlap_val = matrix[code_a][code_b]
            if code_a == code_b:
                color_val = "100.0"
            else:
                color_val = f"{overlap_val:.2f}%"
            sys.stdout.write(f"| {color_val:^{col_width}}")
        sys.stdout.write("\n")
    print("=" * 100)

    # 7. Print Detailed Analysis for High Overlaps (>10%)
    print("\n" + "=" * 100)
    print("DETAILED PAIRWISE STOCK OVERLAP ANALYSIS (>10.0% overlap)")
    print("=" * 100)
    
    sorted_pairs = sorted(detailed_overlaps.items(), key=lambda x: -x[1][0])
    high_overlap_found = False
    
    for pair, (overlap, details) in sorted_pairs:
        if overlap < 10.0:
            continue
            
        high_overlap_found = True
        code_a, code_b = pair
        name_a = fund_labels[code_a]
        name_b = fund_labels[code_b]
        
        print(f"\n🔥 Overlap between '{name_a}' and '{name_b}': {overlap:.2f}%")
        print("-" * 100)
        print(f"{'Stock / Holding Name':<45} | {'Alloc A %':<15} | {'Alloc B %':<15} | {'Overlap Contribution %':<20}")
        print("-" * 100)
        for d in details[:8]:  # Print top 8 overlapping holdings
            print(f"{d['company_name']:<45} | {d['alloc_a']:<15.2f} | {d['alloc_b']:<15.2f} | {d['intersection']:<20.2f}")
        if len(details) > 8:
            print(f"...and {len(details) - 8} more overlapping stock(s)")
        print("-" * 100)

    if not high_overlap_found:
        print("\nNice! All your mutual funds have extremely low portfolio overlaps (< 10%). Your diversification is excellent!")
        print("=" * 100)

    # 8. Write results to Google Sheet
    try:
        settings = load_settings(SETTINGS_PATH)
        sheet_id = settings.google_sheet.spreadsheet_id
        if sheet_id:
            log.info("Writing overlap report to Google Sheet spreadsheet ID %s...", sheet_id)
            writer = OverlapSheetWriter(
                spreadsheet_id=sheet_id,
                worksheet_name=OVERLAP_TAB_DEFAULT,
                credentials_path=CREDENTIALS_PATH,
                token_path=TOKEN_PATH,
            )
            writer.write_overlap_report(active_codes, fund_labels, matrix, sorted_pairs)
            print(f"\n✅ Portfolio Overlap report successfully written to Google Sheet tab '{OVERLAP_TAB_DEFAULT}'!")
        else:
            log.warning("No Google Sheet Spreadsheet ID configured. Skipping Sheet write.")
    except Exception as e:
        log.exception("Failed to write Portfolio Overlap report to Google Sheet:")

    log.info("Portfolio overlap calculation completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
