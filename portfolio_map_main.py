"""Portfolio Asset Map & Allocation Analyzer CLI.

Aggregates individual stock-level holdings and sector weightages across
all mutual funds inside config/funds.yaml using custom investment weights,
writes reports to Google Sheets, and saves cached JSON for web dashboards.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import logging
from pathlib import Path
import sys

from mfhelper.config import load_funds, load_settings
from mfhelper.overlap import (
    fetch_fund_holdings,
    fetch_isin_from_amfi,
    fetch_tickertape_sitemap_urls,
    get_tickertape_mappings_path,
    load_cached_mappings,
    resolve_mfid_by_isin,
    save_cached_mappings,
)
from mfhelper.portfolio_map_sheet import PortfolioMapSheetWriter, ALLOCATION_TAB_DEFAULT

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"

FUNDS_PATH_DEFAULT = CONFIG_DIR / "funds.yaml"
SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
CREDENTIALS_PATH = CONFIG_DIR / "credentials.json"
TOKEN_PATH = DATA_DIR / "token.json"
CACHE_FILE_PATH = DATA_DIR / "combined_portfolio_allocation.json"


def _configure_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / "mfhelper_portfoliomap.log"
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
        prog="mfhelper-portfolio-map",
        description="Compute consolidated stock-level and sector-level exposures across your funds.",
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
    log = logging.getLogger("mfhelper.portfoliomap_main")
    log.info("=== MFHelper Consolidated Portfolio Map starting ===")
    
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

    # 2. Get ISINs from AMFI
    codes = [str(f.code) for f in funds]
    try:
        code_to_isin, code_to_name = fetch_isin_from_amfi(codes)
    except Exception as e:
        log.exception("Failed to fetch ISIN codes from AMFI:")
        return 3

    # 3. Resolve Tickertape mappings
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

    # 4. Normalize portfolio investment weights (Defaulting to Equal Weighting if missing)
    weights = {}
    specified = [f for f in funds if f.weight is not None]
    
    if len(specified) == len(funds):
        # All specified, normalize to sum to 100%
        total_spec = sum(f.weight for f in funds)
        for f in funds:
            weights[f.code] = (f.weight / total_spec) * 100.0
    elif len(specified) > 0:
        # Mixed: some specified, divide remainder equally
        total_spec = sum(f.weight for f in specified)
        remaining_weight = max(0.0, 100.0 - total_spec)
        unspecified = [f for f in funds if f.weight is None]
        share = remaining_weight / len(unspecified) if unspecified else 0.0
        for f in funds:
            if f.weight is not None:
                weights[f.code] = f.weight
            else:
                weights[f.code] = share
    else:
        # Equal weighting
        share = 100.0 / len(funds)
        for f in funds:
            weights[f.code] = share

    # Log allocations
    log.info("Normalized Fund Investment Weights for consolidation:")
    for f in funds:
        log.info("  - %s: %.2f%%", f.name or code_to_name[str(f.code)], weights.get(f.code, 0.0))

    # 5. Fetch live holdings and aggregate weights
    consolidated_stocks = {}
    consolidated_sectors = {}
    fund_holdings_dict = {}
    
    for fund in funds:
        mf_id = mapped_ids.get(fund.code)
        fund_weight = weights.get(fund.code, 0.0)
        
        if not mf_id or fund_weight <= 0.0:
            continue
            
        try:
            holdings = fetch_fund_holdings(mf_id)
            fund_holdings_dict[fund.code] = [
                {
                    "company_name": h.company_name,
                    "allocation_pct": h.allocation_pct,
                    "sid": h.sid,
                    "ticker": h.ticker,
                    "instrument_type": h.instrument_type
                }
                for h in holdings
            ]
            for h in holdings:
                # Aggregate Stock Weights
                # Formula: Combined Stock Weight = (Fund Weight / 100) * Stock Weight inside Fund
                contrib = (fund_weight / 100.0) * h.allocation_pct
                
                stock_key = h.sid if h.sid else h.company_name.lower().strip()
                if stock_key not in consolidated_stocks:
                    consolidated_stocks[stock_key] = {
                        "company_name": h.company_name,
                        "ticker": h.ticker,
                        "combined_weight": 0.0,
                    }
                consolidated_stocks[stock_key]["combined_weight"] += contrib
                
                # Aggregate Sector Weights
                sec_name = h.instrument_type if h.instrument_type != "Equity" else (h.company_name if not h.sid else "Equity")
                # Wait, lets use the sector field or fall back to instrument type
                sec_label = h.instrument_type  # Default to instrument (e.g. Cash, Equity, Debt)
                
                # If it is stock/equity, Tickertape has a sector field in holdings but we default to "Equity" or generic
                # Actually, let us group by instrument type / category
                if h.instrument_type == "Equity":
                    sec_label = "Equity"
                elif h.instrument_type == "Others" or "borrow" in h.company_name.lower() or "receivable" in h.company_name.lower():
                    sec_label = "Cash & Cash Equivalents"
                else:
                    sec_label = h.instrument_type
                    
                if sec_label not in consolidated_sectors:
                    consolidated_sectors[sec_label] = 0.0
                consolidated_sectors[sec_label] += contrib
                
        except Exception as e:
            log.warning("Failed to fetch holdings for fund %s: %s", fund.code, e)

    if not consolidated_stocks:
        log.error("Could not fetch any holdings to map portfolio.")
        return 2

    # 6. Sort and Compile
    stocks_sorted = sorted(consolidated_stocks.values(), key=lambda x: -x["combined_weight"])
    sectors_sorted = sorted(consolidated_sectors.items(), key=lambda x: -x[1])

    # Print Terminal Summary
    print("\n" + "=" * 100)
    print("🔥 CONSOLIDATED TOP 15 STOCK HOLDINGS IN PORTFOLIO")
    print("=" * 100)
    print(f"{'Stock / Holding Name':<45} | {'Ticker':<15} | {'Combined Portfolio Weight %':<20}")
    print("-" * 100)
    for st in stocks_sorted[:15]:
        ticker = st["ticker"] or "n/a"
        print(f"{st['company_name']:<45} | {ticker:<15} | {st['combined_weight']:<20.2f}%")
    print("=" * 100)

    print("\n" + "=" * 100)
    print("🧱 CONSOLIDATED ASSET ALLOCATION")
    print("=" * 100)
    print(f"{'Asset Class / Category':<45} | {'Combined Weight %':<20}")
    print("-" * 100)
    for sec_name, weight in sectors_sorted:
        print(f"{sec_name:<45} | {weight:<20.2f}%")
    print("=" * 100)

    # 7. Write to Google Sheets
    try:
        settings = load_settings(SETTINGS_PATH)
        sheet_id = settings.google_sheet.spreadsheet_id
        if sheet_id:
            log.info("Writing combined allocation report to Google Sheet...")
            writer = PortfolioMapSheetWriter(
                spreadsheet_id=sheet_id,
                worksheet_name=ALLOCATION_TAB_DEFAULT,
                credentials_path=CREDENTIALS_PATH,
                token_path=TOKEN_PATH,
            )
            writer.write_allocation_report(sectors_sorted, stocks_sorted[:15])
            print(f"\n✅ Combined Allocation report successfully written to Google Sheet tab '{ALLOCATION_TAB_DEFAULT}'!")
        else:
            log.warning("No Google Sheet ID configured. Skipping Sheet write.")
    except Exception as e:
        log.exception("Failed to write Consolidated Allocation report to Google Sheet:")

    # 8. Save cached JSON for HTML dashboard
    try:
        cache_payload = {
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sectors": [{"name": k, "weight": v} for k, v in sectors_sorted],
            "stocks": [{"name": s["company_name"], "weight": s["combined_weight"]} for s in stocks_sorted[:15]],
            "fund_holdings": fund_holdings_dict
        }
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with CACHE_FILE_PATH.open("w", encoding="utf-8") as f:
            json.dump(cache_payload, f, indent=2)
        log.info("Successfully cached consolidated allocation data inside: %s", CACHE_FILE_PATH)
    except Exception as e:
        log.warning("Failed to save allocation cache file: %s", e)

    log.info("Consolidated Portfolio Map completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
